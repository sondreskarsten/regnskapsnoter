"""Tests for the Pydantic schema generators in regnskap_no.prompts.

Audit B5 flagged that ``pydantic_for_calc_arc``, ``pydantic_for_axis_dict``,
and ``pydantic_for_hypercube`` had ZERO tests. This file exercises all
three using real concept IDs and axes from v1.0.3.

These generators are what the integration design promised would produce
typed extraction prompts from the taxonomy. Without them tested, the
LLM-driven typed extraction layer is unverifiable.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from regnskap_no import api
from regnskap_no.prompts import (
    pydantic_for_axis_dict,
    pydantic_for_calc_arc,
    pydantic_for_hypercube,
)


# ---- pydantic_for_calc_arc ----

class TestPydanticForCalcArc:
    def test_balanse_eiendeler_arc_has_two_children(self):
        """Eiendeler under balanse role splits into Anleggsmidler + Omlopsmidler."""
        Model = pydantic_for_calc_arc(
            "regnskap-no:Eiendeler",
            role="[620000] Balanse",
        )
        # Field names derive from concept IDs, lowercased + underscored
        fields = Model.model_fields.keys()
        assert "anleggsmidler" in fields
        assert "omlopsmidler" in fields
        # Plus the parent total
        assert "sum_total" in fields

    def test_calc_arc_metadata_attached(self):
        """The model carries ``__regnskap_calc_arc__`` for downstream validation."""
        Model = pydantic_for_calc_arc(
            "regnskap-no:Eiendeler",
            role="[620000] Balanse",
        )
        meta = Model.__regnskap_calc_arc__
        assert meta["parent"] == "regnskap-no:Eiendeler"
        assert meta["role"] == "[620000] Balanse"
        # Children list is stable: name + weight pairs
        names = [n for n, w in meta["children"]]
        weights = [w for n, w in meta["children"]]
        assert "anleggsmidler" in names
        assert "omlopsmidler" in names
        assert all(w in (1.0, -1.0) for w in weights)

    def test_calc_arc_fields_are_optional_floats(self):
        """LLM may legitimately omit a figure that's not in the source PDF."""
        Model = pydantic_for_calc_arc(
            "regnskap-no:Eiendeler",
            role="[620000] Balanse",
        )
        # Instantiate with no values — must not raise
        instance = Model()
        assert instance.anleggsmidler is None
        assert instance.omlopsmidler is None

    def test_calc_arc_accepts_partial_values(self):
        Model = pydantic_for_calc_arc(
            "regnskap-no:Eiendeler",
            role="[620000] Balanse",
        )
        instance = Model(anleggsmidler=100.0, omlopsmidler=200.0, sum_total=300.0)
        assert instance.anleggsmidler == 100.0
        assert instance.sum_total == 300.0

    def test_calc_arc_unknown_parent_raises(self):
        with pytest.raises(ValueError, match="No calc-arc children"):
            pydantic_for_calc_arc(
                "regnskap-no:NotARealConcept",
                role="[620000] Balanse",
            )

    def test_calc_arc_unknown_role_raises(self):
        with pytest.raises(ValueError, match="No calc-arc children"):
            pydantic_for_calc_arc(
                "regnskap-no:Eiendeler",
                role="not-a-real-role",
            )


# ---- pydantic_for_axis_dict ----

class TestPydanticForAxisDict:
    def test_egenkapital_komponent_axis(self):
        """EgenkapitalKomponentAxis has 6 members (Aksjekapital, Overkurs, ...)."""
        Model = pydantic_for_axis_dict("regnskap-no:EgenkapitalKomponentAxis")
        fields = Model.model_fields.keys()
        # Each member yields one field (name shape: snake-case minus _member suffix)
        assert len(fields) >= 5
        # Aksjekapital is a known member
        assert any("aksjekapital" in f for f in fields)

    def test_axis_dict_fields_optional_float(self):
        Model = pydantic_for_axis_dict("regnskap-no:EgenkapitalKomponentAxis")
        # Empty instance is valid
        instance = Model()
        for f in Model.model_fields:
            assert getattr(instance, f) is None

    def test_axis_dict_with_int_value_type(self):
        Model = pydantic_for_axis_dict(
            "regnskap-no:EgenkapitalKomponentAxis", value_type=int,
        )
        # Field type became Optional[int]
        for f, info in Model.model_fields.items():
            ann = info.annotation
            # Optional[int] = Union[int, None] in pydantic
            ann_str = str(ann).lower()
            assert "int" in ann_str

    def test_axis_dict_unknown_axis_raises(self):
        with pytest.raises(ValueError, match="no members"):
            pydantic_for_axis_dict("regnskap-no:NotAnAxis")


# ---- pydantic_for_hypercube ----

class TestPydanticForHypercube:
    def test_egenkapital_movement_hypercube(self):
        """Real Egenkapital movement table: 6 components × 8 events."""
        Model = pydantic_for_hypercube(
            primary_concepts=["regnskap-no:Egenkapital"],
            row_axis="regnskap-no:EgenkapitalKomponentAxis",
            col_axis="regnskap-no:EgenkapitalEndringAxis",
            model_name="EgenkapitalRollforward",
        )
        # Field name from concept_id
        assert "egenkapital" in Model.model_fields
        # Hypercube metadata attached
        meta = Model.__regnskap_hypercube__
        assert meta["primary_concepts"] == ["regnskap-no:Egenkapital"]
        assert meta["row_axis"] == "regnskap-no:EgenkapitalKomponentAxis"
        assert meta["col_axis"] == "regnskap-no:EgenkapitalEndringAxis"
        assert len(meta["row_members"]) >= 5
        assert len(meta["col_members"]) >= 5

    def test_hypercube_field_is_nested_dict(self):
        Model = pydantic_for_hypercube(
            primary_concepts=["regnskap-no:Egenkapital"],
            row_axis="regnskap-no:EgenkapitalKomponentAxis",
            col_axis="regnskap-no:EgenkapitalEndringAxis",
        )
        # Default is empty dict; nested dict structure typed (str -> str -> Optional[float])
        instance = Model()
        assert instance.egenkapital == {}

        # Populate part of the cube
        instance2 = Model(
            egenkapital={
                "regnskap-no:AksjekapitalMember": {
                    "regnskap-no:InngaendeBalanseMember": 30000.0,
                    "regnskap-no:UtgaendeBalanseMember": 30000.0,
                }
            }
        )
        assert instance2.egenkapital["regnskap-no:AksjekapitalMember"][
            "regnskap-no:InngaendeBalanseMember"
        ] == 30000.0

    def test_hypercube_two_primaries(self):
        Model = pydantic_for_hypercube(
            primary_concepts=[
                "regnskap-no:Egenkapital",
                "regnskap-no:Eiendeler",
            ],
            row_axis="regnskap-no:EgenkapitalKomponentAxis",
            col_axis="regnskap-no:EgenkapitalEndringAxis",
        )
        # Both primaries become fields
        assert "egenkapital" in Model.model_fields
        assert "eiendeler" in Model.model_fields

    def test_hypercube_missing_axis_members_raises(self):
        with pytest.raises(ValueError, match="must have members"):
            pydantic_for_hypercube(
                primary_concepts=["regnskap-no:Egenkapital"],
                row_axis="regnskap-no:NotAnAxis",
                col_axis="regnskap-no:EgenkapitalEndringAxis",
            )


# ---- Integration: roundtrip through JSON ----

class TestSchemaJsonRoundtrip:
    def test_calc_arc_model_serialises_to_json(self):
        """The generated model must round-trip through JSON cleanly so the
        LLM can return its output as JSON conforming to the schema."""
        Model = pydantic_for_calc_arc(
            "regnskap-no:Eiendeler",
            role="[620000] Balanse",
        )
        instance = Model(anleggsmidler=100.0, omlopsmidler=200.0, sum_total=300.0)
        s = instance.model_dump_json()
        roundtrip = Model.model_validate_json(s)
        assert roundtrip.anleggsmidler == 100.0
        assert roundtrip.sum_total == 300.0

    def test_calc_arc_json_schema_is_valid(self):
        """The model produces a JSON Schema that an LLM can be guided by."""
        Model = pydantic_for_calc_arc(
            "regnskap-no:Eiendeler",
            role="[620000] Balanse",
        )
        schema = Model.model_json_schema()
        assert "properties" in schema
        assert "anleggsmidler" in schema["properties"]
