"""Fact-level validation for regnskapsnoter extractions.

The bundled SHACL shapes (in regnskap-no/data/shapes.ttl) handle structural
constraints on the taxonomy itself. This module adds Python-side checks on the
EXTRACTED FACTS that are emitted as WADM annotations, since SHACL alone can't
easily express things like "if you observe SumEiendeler and Anleggsmidler and
Omlopsmidler, the first must equal the sum of the latter two within tolerance"
without first lifting the WADM into a custom RDF shape — and most of our
downstream consumers want the failures as Pydantic objects, not RDF report
text.

Validators:

- :func:`validate_calc_arc_consistency` — sums of calc-arc children must equal
  parent within tolerance.
- :func:`validate_period_attributes` — instant concepts need ``periodEnd``;
  duration concepts need ``periodStart`` + ``periodEnd``.
- :func:`validate_dimension_members` — annotation dimensions reference valid
  axis members of declared axes.
- :func:`validate_facts` — runs all of the above. Returns a
  :class:`FactValidationReport` with passing/failing annotations.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from regnskap_no import api as taxonomy_api

from regnskapsnoter_wadm import Annotation


# -- Numeric parsing ----------------------------------------------------

def _parse_value(value_text: str) -> Optional[float]:
    """Parse a value string into a float.

    Handles Norwegian thousands-separated numbers (``"12 345 678"``),
    parenthesised negatives (``"(123)"``), and ASCII/Unicode minus.
    """
    if value_text is None:
        return None
    s = value_text.strip()
    if not s:
        return None
    # Parenthesised negative
    paren = False
    if s.startswith("(") and s.endswith(")"):
        paren = True
        s = s[1:-1].strip()
    # Replace various minus characters with ASCII
    for ch in "\u2010\u2011\u2012\u2013\u2014\u2212":
        s = s.replace(ch, "-")
    # Strip thousands separators (space and non-breaking space)
    s = s.replace(" ", "").replace("\u00a0", "")
    # Norwegian decimal comma → ASCII dot
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if paren else v


# -- Failure types ------------------------------------------------------

@dataclass
class FactFailure:
    annotation_id: str
    rule: str           # "calc-arc" | "period" | "dimension" | "balance"
    severity: str       # "violation" | "warning" | "info"
    message: str
    expected: Optional[float] = None
    actual: Optional[float] = None
    diff: Optional[float] = None


@dataclass
class FactValidationReport:
    passing: List[Annotation] = field(default_factory=list)
    failing: List[Tuple[Annotation, List[FactFailure]]] = field(default_factory=list)

    @property
    def conforms(self) -> bool:
        return not self.failing

    @property
    def n_total(self) -> int:
        return len(self.passing) + len(self.failing)


# -- Helpers ------------------------------------------------------------

def _concept_id_of(ann: Annotation) -> Optional[str]:
    for body in ann.body:
        if body.type == "SpecificResource" and body.purpose == "classifying":
            return body.source
    return None


def _value_text_of(ann: Annotation) -> Optional[str]:
    for body in ann.body:
        if body.type == "TextualBody" and body.purpose == "tagging":
            return body.value
    return None


# -- Validators ---------------------------------------------------------

def validate_period_attributes(ann: Annotation) -> List[FactFailure]:
    """An instant concept needs ``periodEnd``; a duration concept needs both."""
    out: List[FactFailure] = []
    pt = ann.period_type
    if pt == "instant" and not ann.period_end:
        out.append(FactFailure(
            annotation_id=ann.id, rule="period", severity="violation",
            message="instant concept missing registrum:periodEnd",
        ))
    if pt == "duration":
        if not ann.period_end:
            out.append(FactFailure(
                annotation_id=ann.id, rule="period", severity="violation",
                message="duration concept missing registrum:periodEnd",
            ))
        if not ann.period_start:
            out.append(FactFailure(
                annotation_id=ann.id, rule="period", severity="violation",
                message="duration concept missing registrum:periodStart",
            ))
    return out


def validate_dimension_members(ann: Annotation) -> List[FactFailure]:
    """Each dimensions[axis_id] must be a real member of that axis."""
    out: List[FactFailure] = []
    if not ann.dimensions:
        return out
    for axis_id, member_id in ann.dimensions.items():
        members = taxonomy_api.get_axis_members(axis_id)
        if not members:
            out.append(FactFailure(
                annotation_id=ann.id, rule="dimension", severity="violation",
                message=f"unknown axis: {axis_id}",
            ))
            continue
        ids = {m.member_id for m in members}
        if member_id not in ids:
            out.append(FactFailure(
                annotation_id=ann.id, rule="dimension", severity="violation",
                message=f"member {member_id!r} not in axis {axis_id}",
            ))
    return out


def validate_calc_arc_consistency(
    annotations: List[Annotation],
    *,
    tolerance: float = 1.0,
) -> Dict[str, List[FactFailure]]:
    """Group annotations by (period_end, role-namespace) and check parent = sum(children).

    Returns a mapping ``annotation_id → list[FactFailure]``. Annotations whose
    concept is not a calc-arc parent for which we have ALL children get no
    finding (validation is best-effort).

    Tolerance is in NOK (default 1 NOK rounding tolerance).
    """
    failures: Dict[str, List[FactFailure]] = defaultdict(list)

    # Index annotations by (period_end, concept_id) → numeric value
    by_period_concept: Dict[Tuple[str, str], List[Annotation]] = defaultdict(list)
    for ann in annotations:
        cid = _concept_id_of(ann)
        if cid is None:
            continue
        period_key = ann.period_end or ""
        by_period_concept[(period_key, cid)].append(ann)

    # For each (period_end, parent_id) where we have a value, look up calc arcs
    # and compare to the sum of child values present in the same period.
    for (period_end, cid), parent_anns in by_period_concept.items():
        arcs = taxonomy_api._calc_arcs()
        children_arcs = [a for a in arcs if a.parent_id == cid]
        if not children_arcs:
            continue

        # Pick the parent value: latest annotation's TextualBody
        parent_value: Optional[float] = None
        parent_ann_id: Optional[str] = None
        for pa in parent_anns:
            v = _parse_value(_value_text_of(pa))
            if v is not None:
                parent_value = v
                parent_ann_id = pa.id
                break
        if parent_value is None:
            continue

        # Sum child values present in the same period
        total = 0.0
        any_child = False
        missing_children: List[str] = []
        for arc in children_arcs:
            child_anns = by_period_concept.get((period_end, arc.child_id), [])
            child_v = None
            for ca in child_anns:
                child_v = _parse_value(_value_text_of(ca))
                if child_v is not None:
                    break
            if child_v is None:
                missing_children.append(arc.child_id)
                continue
            any_child = True
            total += arc.weight * child_v

        if not any_child:
            # No child values to compare against — cannot validate.
            continue
        if missing_children:
            # Don't fire on partial views — a calc-arc needs all children.
            continue

        diff = parent_value - total
        if abs(diff) > tolerance:
            failures[parent_ann_id].append(FactFailure(
                annotation_id=parent_ann_id,
                rule="calc-arc",
                severity="violation",
                message=(
                    f"{cid} = {parent_value:.2f} but sum(children) = {total:.2f} "
                    f"(diff {diff:+.2f}, tolerance {tolerance})"
                ),
                expected=total,
                actual=parent_value,
                diff=diff,
            ))

    return failures


def validate_facts(
    annotations: List[Annotation],
    *,
    calc_arc_tolerance: float = 1.0,
) -> FactValidationReport:
    """Run all validators across a batch of annotations."""
    arc_failures = validate_calc_arc_consistency(
        annotations, tolerance=calc_arc_tolerance,
    )

    report = FactValidationReport()
    for ann in annotations:
        fails: List[FactFailure] = []
        fails.extend(validate_period_attributes(ann))
        fails.extend(validate_dimension_members(ann))
        if ann.id in arc_failures:
            fails.extend(arc_failures[ann.id])
        if fails:
            report.failing.append((ann, fails))
        else:
            report.passing.append(ann)
    return report
