"""regnskap-no — Norwegian regnskap noter taxonomy as a Python wheel.

Source of truth: github.com/sondreskarsten/regnskapnoter-taxonomy

This wheel ships the build artifacts (Parquet + Turtle + JSON-LD + SHACL shapes)
and provides typed lookup helpers. It does NOT do extraction, OCR, or
canonicalisation — those live in regnskapsnoter-pipeline + noter-canonicalizer.

Quick start:

    from regnskap_no import api
    sum_e = api.get_concept("regnskap-no:SumEiendeler")
    print(sum_e.period_type, sum_e.balance, sum_e.standard_label("nb"))

    # Find concepts by Norwegian label
    matches = api.search_label("Sum eiendeler", lang="nb")
    for m in matches:
        print(m.concept_id, m.role, m.text)

    # Get the children of a calc-arc parent
    children = api.get_calc_children("regnskap-no:SumEiendeler",
                                      role="resultatregnskap-etter-art")
"""
from __future__ import annotations

from . import api  # re-export
from .api import (
    Concept,
    Axis,
    AxisMember,
    Label,
    CalcArc,
    Mapping,
    Reference,
    get_concept,
    get_axis,
    get_axis_members,
    get_labels,
    search_label,
    get_calc_children,
    get_mappings,
    get_references,
    list_concepts,
    list_axes,
    DATA_DIR,
)

__version__ = "1.0.3"

__all__ = [
    "api",
    "Concept", "Axis", "AxisMember", "Label", "CalcArc", "Mapping", "Reference",
    "get_concept", "get_axis", "get_axis_members",
    "get_labels", "search_label",
    "get_calc_children", "get_mappings", "get_references",
    "list_concepts", "list_axes",
    "DATA_DIR",
]
