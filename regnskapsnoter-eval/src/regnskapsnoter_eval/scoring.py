"""Scoring primitives — port of ``ocr-cascade-eval/audit/build_v2_audit.py``.

The core matcher is :func:`number_present`. It finds an integer value in
OCR output text by trying both:

- the Norwegian thousands-grouped form (``1 234 567`` with optional whitespace
  between any group)
- the digit-by-digit form (``1234567``, also tolerating whitespace between
  digits in case OCR over-segmented)

Sign handling: a leading ASCII or Unicode minus, or a parenthesised negative,
is treated as the sign of the number being matched.

This file is the ONLY place in the repo where "did OCR find this number?" is
defined. All voter and consensus scoring routes through it so any change to
the matcher applies everywhere consistently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from docling_core.types.doc.page import TextCell


# -- Number matcher --

_PAREN_NEG_RE = re.compile(r"\(\s*([\d\s.,]+)\s*\)")


def number_present(n: int, text: str) -> bool:
    """True iff the integer ``n`` appears in ``text``.

    Matches:
    - grouped:  ``1 234 567`` with any whitespace between groups
    - digit-by-digit: ``1234567`` with optional whitespace anywhere
    - sign: ASCII minus, Unicode minus (U+2212), or surrounding parentheses
    """
    if n is None:
        return False

    # Normalise Unicode minus / hyphen variants to ASCII before matching
    for ch in "\u2010\u2011\u2012\u2013\u2014\u2212":
        text = text.replace(ch, "-")

    n_int = int(round(n))
    sign = "-" if n_int < 0 else ""
    n_abs = abs(n_int)

    if n_abs == 0:
        # A bare 0 is too noisy to match without context; require a separator
        return bool(re.search(r"(?:^|\s|\n)0(?:\s|$|\n|[.,])", text))

    s = str(n_abs)
    s_rev = s[::-1]
    groups = [s_rev[i:i + 3][::-1] for i in range(0, len(s_rev), 3)][::-1]

    pat_grouped = sign + r"\s*".join(re.escape(g) for g in groups)
    pat_digits = sign + r"\s*".join(re.escape(d) for d in s)

    if re.search(pat_grouped, text):
        return True
    if re.search(pat_digits, text):
        return True

    # Parenthesised negative
    if sign == "-":
        for m in _PAREN_NEG_RE.finditer(text):
            inner = m.group(1)
            if re.search(r"\s*".join(re.escape(g) for g in groups), inner):
                return True
            if re.search(r"\s*".join(re.escape(d) for d in s), inner):
                return True
    return False


# -- Score primitives --

@dataclass
class EngineScore:
    """Per-(engine, orgnr) result."""

    engine: str
    orgnr: str
    truth_numbers: Set[int]
    recovered: Set[int]

    @property
    def hits(self) -> int:
        return len(self.recovered)

    @property
    def total(self) -> int:
        return len(self.truth_numbers)

    @property
    def recall(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def missed(self) -> Set[int]:
        return self.truth_numbers - self.recovered


def score_engine_text(
    *, engine: str, orgnr: str, text: str, truth: Set[int],
) -> EngineScore:
    """Score a single engine's text output for one orgnr against its truth set."""
    rec = {n for n in truth if number_present(n, text)}
    return EngineScore(engine=engine, orgnr=orgnr, truth_numbers=set(truth),
                       recovered=rec)


def _cells_to_text(cells: Iterable[TextCell]) -> str:
    return "\n".join(c.text for c in cells)


def score_per_voter(
    *,
    orgnr: str,
    per_voter_cells: Dict[str, Iterable[TextCell]],
    truth: Set[int],
) -> Dict[str, EngineScore]:
    out: Dict[str, EngineScore] = {}
    for voter, cells in per_voter_cells.items():
        text = _cells_to_text(cells)
        out[voter] = score_engine_text(
            engine=voter, orgnr=orgnr, text=text, truth=truth,
        )
    return out


@dataclass
class ReliabilityReport:
    """Per-(orgnr, truth_value) cascade reliability."""

    orgnr: str
    truth_value: int
    voters_hit: List[str]
    voters_attempted: List[str]
    n_hit: int
    n_attempted: int
    unanimous: bool
    reliable: bool   # n_hit >= min_voters_for_reliable

    def to_dict(self) -> dict:
        return {
            "orgnr": self.orgnr,
            "truth_value": self.truth_value,
            "voters_hit": list(self.voters_hit),
            "voters_attempted": list(self.voters_attempted),
            "n_hit": self.n_hit,
            "n_attempted": self.n_attempted,
            "unanimous": self.unanimous,
            "reliable": self.reliable,
        }


def score_consensus(
    *,
    orgnr: str,
    per_voter_cells: Dict[str, Iterable[TextCell]],
    truth: Set[int],
    min_voters_for_reliable: int = 7,
) -> List[ReliabilityReport]:
    """For each truth value, count how many voters' text contained it.

    The per-voter granularity (line vs word) doesn't matter for this report
    — we treat each voter's full text as one document and ask "does the
    integer appear anywhere in this voter's output?". This is the same
    methodology used in build_v2_audit.py.
    """
    voter_texts = {v: _cells_to_text(cs) for v, cs in per_voter_cells.items()}
    voters = sorted(voter_texts)

    out: List[ReliabilityReport] = []
    for n in sorted(truth):
        hits = [v for v in voters if number_present(n, voter_texts[v])]
        out.append(ReliabilityReport(
            orgnr=orgnr,
            truth_value=n,
            voters_hit=hits,
            voters_attempted=voters,
            n_hit=len(hits),
            n_attempted=len(voters),
            unanimous=len(hits) == len(voters),
            reliable=len(hits) >= min_voters_for_reliable,
        ))
    return out


@dataclass
class FixtureScore:
    """Aggregate over the whole fixture."""

    n_orgnrs: int = 0
    n_truth_values: int = 0
    n_unanimous: int = 0
    n_reliable: int = 0
    n_universal_miss: int = 0
    per_voter_recall: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # voter -> (hits, total)
    per_orgnr: Dict[str, List[ReliabilityReport]] = field(default_factory=dict)

    @property
    def fraction_unanimous(self) -> float:
        return self.n_unanimous / self.n_truth_values if self.n_truth_values else 0.0

    @property
    def fraction_reliable(self) -> float:
        return self.n_reliable / self.n_truth_values if self.n_truth_values else 0.0


def score_fixture(
    *,
    cells_per_orgnr_per_voter: Dict[str, Dict[str, Iterable[TextCell]]],
    truth_per_orgnr: Dict[str, Set[int]],
    min_voters_for_reliable: int = 7,
) -> FixtureScore:
    """Score every (orgnr, truth_value) across the whole fixture.

    ``cells_per_orgnr_per_voter[orgnr][voter] = list[TextCell]``
    ``truth_per_orgnr[orgnr] = set[int]``
    """
    fs = FixtureScore()
    fs.n_orgnrs = len(cells_per_orgnr_per_voter)

    voter_hits: Dict[str, int] = {}
    voter_totals: Dict[str, int] = {}

    for orgnr, per_voter in cells_per_orgnr_per_voter.items():
        truth = truth_per_orgnr.get(orgnr, set())
        if not truth:
            continue
        reports = score_consensus(
            orgnr=orgnr,
            per_voter_cells=per_voter,
            truth=truth,
            min_voters_for_reliable=min_voters_for_reliable,
        )
        fs.per_orgnr[orgnr] = reports
        fs.n_truth_values += len(reports)
        fs.n_unanimous += sum(1 for r in reports if r.unanimous)
        fs.n_reliable += sum(1 for r in reports if r.reliable)
        fs.n_universal_miss += sum(1 for r in reports if r.n_hit == 0)

        # Per-voter recall: how many of this orgnr's truth values did each voter recover?
        per_voter_scores = score_per_voter(
            orgnr=orgnr,
            per_voter_cells=per_voter,
            truth=truth,
        )
        for voter, sc in per_voter_scores.items():
            voter_hits[voter] = voter_hits.get(voter, 0) + sc.hits
            voter_totals[voter] = voter_totals.get(voter, 0) + sc.total

    fs.per_voter_recall = {v: (voter_hits[v], voter_totals[v]) for v in voter_hits}
    return fs
