"""Shadow-mode diff between v1 and v2 fact extractions.

Audit C11 closed. Core operations:

  diff_facts(v1, v2) → list of DiffEntry per (orgnr, concept_id, period_end)
  per_concept_drift(diff_entries) → DriftReport with per-concept counts
  per_orgnr_summary(diff_entries) → DriftReport with per-orgnr counts
  write_diff_parquet(diff_entries, path) → flat parquet for further analysis

Design notes:

- A Fact is identified by (orgnr, concept_id, period_end). Two facts on
  the same key from v1 and v2 are *comparable*. The values may differ.
- A "match" is exact integer equality (no fuzzy tolerance). The migration
  audit can apply tolerance downstream — for the v1→v2 diff itself, we
  want raw signal: did v2 reproduce the v1 number, did it change, did it
  miss it, or did it add a new fact?
- DiffEntry.kind ∈ {"agree", "disagree", "v1_only", "v2_only"}.
- The same key can appear once at most in any DiffEntry — that's the
  point. If your input has duplicates per key, dedup upstream (or pass
  ``dedup="last"`` to ``diff_facts``).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Fact:
    """A single fact extracted from one årsregnskap.

    Attributes:
        orgnr: 9-digit Norwegian organisation number.
        concept_id: prefixed regnskap-no concept ID (e.g.
            ``regnskap-no:Eiendeler``).
        value: numeric value. Float to preserve negative + non-integer
            values; rounded to int when comparing for diff equality.
        period_end: ISO period end (``YYYY-MM-DD``).
        source: pipeline tag, e.g. ``"v1"`` or ``"v2"``. Used by callers
            and propagated into DiffEntry; not part of the dedup key.
    """

    orgnr: str
    concept_id: str
    value: float
    period_end: str
    source: str = ""


@dataclass
class DiffEntry:
    """One row of the v1↔v2 diff.

    ``kind`` is one of:
      - ``"agree"``: v1 and v2 produced the same integer value
      - ``"disagree"``: both produced a value but they differ
      - ``"v1_only"``: v1 had it, v2 dropped it
      - ``"v2_only"``: v2 added it, v1 had no fact for this key
    """

    orgnr: str
    concept_id: str
    period_end: str
    kind: str
    v1_value: Optional[float]
    v2_value: Optional[float]
    abs_delta: Optional[float] = None
    rel_delta: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _key(f: Fact) -> Tuple[str, str, str]:
    return (f.orgnr, f.concept_id, f.period_end)


def _index(
    facts: Iterable[Fact], *, dedup: str = "error",
) -> Dict[Tuple[str, str, str], Fact]:
    out: Dict[Tuple[str, str, str], Fact] = {}
    for f in facts:
        k = _key(f)
        if k in out:
            if dedup == "error":
                raise ValueError(
                    f"duplicate fact key {k}; pass dedup='last' or 'first' to "
                    "select between duplicates"
                )
            elif dedup == "first":
                continue   # keep the existing
            elif dedup == "last":
                out[k] = f   # overwrite
            else:
                raise ValueError(
                    f"dedup must be 'error', 'first', or 'last'; got {dedup!r}"
                )
        else:
            out[k] = f
    return out


def diff_facts(
    v1: Sequence[Fact],
    v2: Sequence[Fact],
    *,
    dedup: str = "error",
) -> List[DiffEntry]:
    """Compute the per-key diff between two fact sets.

    Args:
        v1, v2: lists of Fact. Each list must have at most one fact per
            ``(orgnr, concept_id, period_end)`` key unless ``dedup`` is
            'first' or 'last'.
        dedup: behaviour on duplicate keys within a single list:
            - ``"error"`` (default): raise ValueError
            - ``"first"``: keep the first occurrence
            - ``"last"``: keep the last occurrence

    Returns:
        List of DiffEntry, one per union of keys across v1 ∪ v2.
    """
    v1_index = _index(v1, dedup=dedup)
    v2_index = _index(v2, dedup=dedup)
    keys = set(v1_index.keys()) | set(v2_index.keys())

    entries: List[DiffEntry] = []
    for k in sorted(keys):
        f1 = v1_index.get(k)
        f2 = v2_index.get(k)
        orgnr, concept_id, period_end = k

        if f1 is not None and f2 is None:
            entries.append(DiffEntry(
                orgnr=orgnr, concept_id=concept_id, period_end=period_end,
                kind="v1_only",
                v1_value=f1.value, v2_value=None,
            ))
        elif f1 is None and f2 is not None:
            entries.append(DiffEntry(
                orgnr=orgnr, concept_id=concept_id, period_end=period_end,
                kind="v2_only",
                v1_value=None, v2_value=f2.value,
            ))
        else:
            assert f1 is not None and f2 is not None
            v1v = int(round(f1.value))
            v2v = int(round(f2.value))
            if v1v == v2v:
                entries.append(DiffEntry(
                    orgnr=orgnr, concept_id=concept_id, period_end=period_end,
                    kind="agree",
                    v1_value=f1.value, v2_value=f2.value,
                    abs_delta=0.0, rel_delta=0.0,
                ))
            else:
                ad = abs(v2v - v1v)
                rd = ad / abs(v1v) if v1v != 0 else math.inf
                entries.append(DiffEntry(
                    orgnr=orgnr, concept_id=concept_id, period_end=period_end,
                    kind="disagree",
                    v1_value=f1.value, v2_value=f2.value,
                    abs_delta=float(ad),
                    rel_delta=float(rd),
                ))
    return entries


# -- Aggregators --

@dataclass
class DriftReport:
    """Aggregated counts for an axis (concept_id or orgnr).

    For each axis value, four counts:
      - n_agree
      - n_disagree
      - n_v1_only
      - n_v2_only

    plus a derived ``agreement_rate`` (n_agree / total over comparable
    facts only — i.e. excludes v2_only and v1_only from denom).
    """

    rows: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def agreement_rate(self, key: str) -> Optional[float]:
        r = self.rows.get(key)
        if r is None:
            return None
        comparable = r["n_agree"] + r["n_disagree"]
        if comparable == 0:
            return None
        return r["n_agree"] / comparable

    def to_records(self) -> List[dict]:
        out = []
        for k, v in sorted(self.rows.items()):
            row = {"key": k, **v}
            row["agreement_rate"] = self.agreement_rate(k)
            out.append(row)
        return out


def _aggregate(
    entries: Iterable[DiffEntry],
    *,
    by: str,
) -> DriftReport:
    """Aggregate diff entries by attribute name."""
    bucket: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"n_agree": 0, "n_disagree": 0, "n_v1_only": 0, "n_v2_only": 0}
    )
    for e in entries:
        key = getattr(e, by)
        if e.kind == "agree":
            bucket[key]["n_agree"] += 1
        elif e.kind == "disagree":
            bucket[key]["n_disagree"] += 1
        elif e.kind == "v1_only":
            bucket[key]["n_v1_only"] += 1
        elif e.kind == "v2_only":
            bucket[key]["n_v2_only"] += 1
    return DriftReport(rows=dict(bucket))


def per_concept_drift(entries: Iterable[DiffEntry]) -> DriftReport:
    """Aggregate the diff by ``concept_id``."""
    return _aggregate(entries, by="concept_id")


def per_orgnr_summary(entries: Iterable[DiffEntry]) -> DriftReport:
    """Aggregate the diff by ``orgnr``."""
    return _aggregate(entries, by="orgnr")


# -- Parquet writer --

def write_diff_parquet(entries: Sequence[DiffEntry], path: str) -> int:
    """Write a flat parquet of the diff entries.

    Schema:
      orgnr: string
      concept_id: string
      period_end: string
      kind: string
      v1_value: double (nullable)
      v2_value: double (nullable)
      abs_delta: double (nullable)
      rel_delta: double (nullable)

    Returns:
        Number of rows written.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema([
        ("orgnr", pa.string()),
        ("concept_id", pa.string()),
        ("period_end", pa.string()),
        ("kind", pa.string()),
        ("v1_value", pa.float64()),
        ("v2_value", pa.float64()),
        ("abs_delta", pa.float64()),
        ("rel_delta", pa.float64()),
    ])

    cols = {
        "orgnr": [], "concept_id": [], "period_end": [], "kind": [],
        "v1_value": [], "v2_value": [], "abs_delta": [], "rel_delta": [],
    }
    for e in entries:
        cols["orgnr"].append(e.orgnr)
        cols["concept_id"].append(e.concept_id)
        cols["period_end"].append(e.period_end)
        cols["kind"].append(e.kind)
        cols["v1_value"].append(e.v1_value)
        cols["v2_value"].append(e.v2_value)
        cols["abs_delta"].append(e.abs_delta)
        # rel_delta may contain math.inf (v1 was 0, v2 wasn't); pyarrow's
        # float64 can hold inf so we don't need special handling
        cols["rel_delta"].append(e.rel_delta)

    table = pa.Table.from_pydict(cols, schema=schema)
    pq.write_table(table, path)
    return table.num_rows
