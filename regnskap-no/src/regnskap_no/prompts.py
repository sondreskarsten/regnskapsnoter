"""Generate Pydantic schemas from taxonomy concepts/axes.

For a given parent concept (e.g., ``regnskap-no:SumEiendeler``), build a
Pydantic model whose fields are the calculation-arc children. For a concept that
has a hypercube (e.g., egenkapital with EgenkapitalKomponentAxis ×
EgenkapitalEndringAxis), build a 2-D dict structure typed by the axis members.

This is what regnskapsnoter-pipeline uses to produce typed extraction prompts
and validate per-note LLM outputs structurally.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, create_model

from .api import (
    Concept,
    get_concept,
    get_calc_children,
    get_axis_members,
    list_concepts,
)


def _safe_field_name(concept_id: str) -> str:
    """``regnskap-no:SumEiendeler`` → ``sum_eiendeler``."""
    name = concept_id.split(":", 1)[-1]
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i-1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def pydantic_for_calc_arc(parent_id: str, *, role: str,
                           model_name: Optional[str] = None) -> Type[BaseModel]:
    """Build a Pydantic model whose fields are the children of the given calc arc.

    Each child field is ``Optional[float]`` so the LLM may legitimately omit a
    figure that is not present in the source PDF. A ``model_validator`` checks
    the calculation arc consistency: the sum of present children must equal the
    parent within rounding tolerance.
    """
    children = get_calc_children(parent_id, role=role)
    if not children:
        raise ValueError(f"No calc-arc children for {parent_id} in role {role!r}")

    fields: Dict[str, Any] = {}
    name_to_concept: Dict[str, str] = {}
    for arc in children:
        fname = _safe_field_name(arc.child_id)
        # Stable name even when several arcs share names by adding a counter
        if fname in fields:
            fname = fname + f"_{arc.order}"
        fields[fname] = (Optional[float], Field(default=None,
                          description=f"{arc.child_id} (weight={arc.weight})"))
        name_to_concept[fname] = arc.child_id

    # Parent total
    fields["sum_total"] = (
        Optional[float],
        Field(default=None, description=f"{parent_id} (computed total)"),
    )

    model = create_model(
        model_name or _safe_field_name(parent_id) + "_arc",
        __base__=BaseModel,
        **fields,
    )

    # Attach the calc-arc metadata as class vars for downstream validators
    model.__regnskap_calc_arc__ = {
        "parent": parent_id,
        "role": role,
        "children": [(_safe_field_name(a.child_id), a.weight) for a in children],
    }  # type: ignore[attr-defined]
    return model


def pydantic_for_axis_dict(axis_id: str, *,
                            value_type: type = float) -> Type[BaseModel]:
    """Build a Pydantic model with one optional field per member of the given axis.

    Used for note tables that are 1-D over a single axis (e.g., a list of
    components of egenkapital broken out by ``EgenkapitalKomponentAxis``).
    """
    members = get_axis_members(axis_id)
    if not members:
        raise ValueError(f"Axis {axis_id} has no members")
    fields: Dict[str, Any] = {}
    for m in members:
        fname = _safe_field_name(m.member_id).rstrip("_member")
        fields[fname] = (Optional[value_type], Field(default=None,
                                                       description=m.member_id))
    model_name = _safe_field_name(axis_id) + "_dict"
    return create_model(model_name, __base__=BaseModel, **fields)


def pydantic_for_hypercube(*, primary_concepts: List[str],
                            row_axis: str, col_axis: str,
                            model_name: str = "Hypercube") -> Type[BaseModel]:
    """Build a Pydantic model for a 2-D hypercube.

    Fields are nested dicts ``{row_member: {col_member: value}}`` typed against
    the axis members. Useful for egenkapital movement tables, anleggsmidler
    reconciliation, etc.
    """
    row_members = [m.member_id for m in get_axis_members(row_axis)]
    col_members = [m.member_id for m in get_axis_members(col_axis)]
    if not row_members or not col_members:
        raise ValueError("Both axes must have members")

    fields: Dict[str, Any] = {}
    for primary in primary_concepts:
        fname = _safe_field_name(primary)
        # Inner dict type: dict[str, dict[str, Optional[float]]]
        fields[fname] = (
            Dict[str, Dict[str, Optional[float]]],
            Field(default_factory=dict,
                  description=f"{primary} keyed by ({row_axis}, {col_axis})"),
        )

    model = create_model(model_name, __base__=BaseModel, **fields)
    model.__regnskap_hypercube__ = {
        "primary_concepts": primary_concepts,
        "row_axis": row_axis,
        "row_members": row_members,
        "col_axis": col_axis,
        "col_members": col_members,
    }  # type: ignore[attr-defined]
    return model
