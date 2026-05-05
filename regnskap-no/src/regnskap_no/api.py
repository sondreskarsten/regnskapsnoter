"""regnskap-no API — typed accessors over the Parquet build artifacts.

All accessors are cached. The first call to any function loads the relevant
Parquet table once; subsequent calls are dict lookups.
"""
from __future__ import annotations

import functools
import unicodedata
from importlib import resources
from pathlib import Path
from typing import Iterator, List, Optional

import pyarrow.parquet as pq
from pydantic import BaseModel, Field

# Locate data dir robustly: when installed from wheel it's under regnskap_no/data;
# when run from source it's the same place.
DATA_DIR: Path = Path(resources.files("regnskap_no") / "data")


# -- Pydantic models ----------------------------------------------------

class Concept(BaseModel):
    """An XBRL-style concept entry."""

    concept_id: str
    namespace: str
    period_type: str  # "instant" | "duration"
    balance: Optional[str] = None  # "debit" | "credit" | None
    data_type: str
    substitution_group: str
    abstract: bool = False
    status: str  # "candidate" | "standard" | "deprecated" | "retired"
    introduced_version: Optional[str] = None
    deprecated_date: Optional[str] = None
    deprecated_replacement: Optional[str] = None
    source_path: Optional[str] = None

    def standard_label(self, lang: str = "nb") -> Optional[str]:
        for lab in get_labels(self.concept_id):
            if lab.lang == lang and lab.role == "standardLabel":
                return lab.text
        return None

    def all_labels(self) -> List["Label"]:
        return get_labels(self.concept_id)


class Axis(BaseModel):
    axis_id: str
    namespace: str
    axis_kind: str
    typed_datatype: Optional[str] = None
    default_member: Optional[str] = None
    status: str
    introduced_version: Optional[str] = None
    deprecated_date: Optional[str] = None
    source_path: Optional[str] = None


class AxisMember(BaseModel):
    axis_id: str
    member_id: str
    parent_member_id: Optional[str] = None
    order: int = 0
    usable: bool = True
    status: str = "standard"


class Label(BaseModel):
    subject_id: str
    subject_kind: str
    lang: str
    role: str
    text: str


class CalcArc(BaseModel):
    role: str
    parent_id: str
    child_id: str
    weight: float = 1.0
    order: int = 0
    applicable_from_fiscal_year: Optional[int] = None
    applicable_to_fiscal_year: Optional[int] = None


class Mapping(BaseModel):
    subject_id: str
    subject_kind: str
    target: Optional[str] = None
    relation: Optional[str] = None  # exactMatch | closeMatch | broadMatch | narrowMatch | relatedMatch
    quality: Optional[str] = None
    note: Optional[str] = None


class Reference(BaseModel):
    subject_id: str
    subject_kind: str
    publisher: str
    document: str
    paragraph: Optional[str] = None
    version: Optional[str] = None
    applicable_from_fiscal_year: Optional[int] = None
    applicable_to_fiscal_year: Optional[int] = None
    note: Optional[str] = None


# -- Loaders (cached) ---------------------------------------------------

@functools.lru_cache(maxsize=None)
def _concepts_table():
    return pq.read_table(DATA_DIR / "concepts.parquet").to_pylist()


@functools.lru_cache(maxsize=None)
def _concepts_index() -> dict[str, Concept]:
    return {row["concept_id"]: Concept(**row) for row in _concepts_table()}


@functools.lru_cache(maxsize=None)
def _axes_index() -> dict[str, Axis]:
    rows = pq.read_table(DATA_DIR / "axes.parquet").to_pylist()
    return {row["axis_id"]: Axis(**row) for row in rows}


@functools.lru_cache(maxsize=None)
def _axis_members() -> List[AxisMember]:
    return [AxisMember(**row) for row in pq.read_table(DATA_DIR / "axis_members.parquet").to_pylist()]


@functools.lru_cache(maxsize=None)
def _labels() -> List[Label]:
    return [Label(**row) for row in pq.read_table(DATA_DIR / "labels.parquet").to_pylist()]


@functools.lru_cache(maxsize=None)
def _labels_by_subject() -> dict[str, List[Label]]:
    out: dict[str, List[Label]] = {}
    for lab in _labels():
        out.setdefault(lab.subject_id, []).append(lab)
    return out


@functools.lru_cache(maxsize=None)
def _calc_arcs() -> List[CalcArc]:
    return [CalcArc(**row) for row in pq.read_table(DATA_DIR / "calc_arcs.parquet").to_pylist()]


@functools.lru_cache(maxsize=None)
def _mappings() -> List[Mapping]:
    rows = pq.read_table(DATA_DIR / "mappings.parquet").to_pylist()
    return [Mapping(**row) for row in rows]


@functools.lru_cache(maxsize=None)
def _references() -> List[Reference]:
    rows = pq.read_table(DATA_DIR / "references.parquet").to_pylist()
    return [Reference(**row) for row in rows]


# -- Public API ---------------------------------------------------------

def get_concept(concept_id: str) -> Optional[Concept]:
    return _concepts_index().get(concept_id)


def list_concepts(*, status: Optional[str] = None) -> Iterator[Concept]:
    for c in _concepts_index().values():
        if status is None or c.status == status:
            yield c


def get_axis(axis_id: str) -> Optional[Axis]:
    return _axes_index().get(axis_id)


def list_axes() -> Iterator[Axis]:
    yield from _axes_index().values()


def get_axis_members(axis_id: str) -> List[AxisMember]:
    return [m for m in _axis_members() if m.axis_id == axis_id]


def get_labels(subject_id: str) -> List[Label]:
    return list(_labels_by_subject().get(subject_id, []))


def _normalise_for_search(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = " ".join(s.split())
    return s.casefold()


def search_label(text: str, *, lang: Optional[str] = None,
                 role: Optional[str] = None,
                 exact: bool = True) -> List[Label]:
    """Find labels matching ``text``.

    With ``exact=True`` (default) returns labels whose text equals ``text`` after
    NFKC + casefold + whitespace-collapse normalisation. With ``exact=False``
    returns labels whose normalised text contains the normalised query.
    """
    needle = _normalise_for_search(text)
    out: List[Label] = []
    for lab in _labels():
        if lang and lab.lang != lang:
            continue
        if role and lab.role != role:
            continue
        hay = _normalise_for_search(lab.text)
        if (exact and hay == needle) or (not exact and needle in hay):
            out.append(lab)
    return out


def get_calc_children(parent_id: str, *, role: Optional[str] = None) -> List[CalcArc]:
    out = [arc for arc in _calc_arcs() if arc.parent_id == parent_id]
    if role:
        out = [a for a in out if a.role == role]
    return sorted(out, key=lambda a: a.order)


def get_mappings(subject_id: str) -> List[Mapping]:
    return [m for m in _mappings() if m.subject_id == subject_id]


def get_references(subject_id: str) -> List[Reference]:
    return [r for r in _references() if r.subject_id == subject_id]
