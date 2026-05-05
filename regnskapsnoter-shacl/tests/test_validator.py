"""Tests for regnskapsnoter-shacl."""
from __future__ import annotations

import pytest

from regnskapsnoter_wadm import build_fact_annotation
from regnskapsnoter_shacl import (
    validate_facts,
    validate_period_attributes,
    validate_dimension_members,
    validate_calc_arc_consistency,
)
from regnskapsnoter_shacl.validator import _parse_value


def test_parse_value_norwegian_thousands():
    assert _parse_value("12 345 678") == 12345678.0


def test_parse_value_paren_negative():
    assert _parse_value("(123)") == -123.0


def test_parse_value_unicode_minus():
    assert _parse_value("\u2212123") == -123.0


def test_parse_value_decimal_comma():
    assert _parse_value("12,5") == 12.5


def test_parse_value_empty():
    assert _parse_value("") is None


def test_period_validator_instant_needs_periodEnd():
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="100",
        # period_end NOT set — should fail
    )
    fails = validate_period_attributes(ann)
    assert len(fails) == 1
    assert fails[0].rule == "period"


def test_period_validator_instant_with_periodEnd_passes():
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="100",
        period_end="2024-12-31",
    )
    fails = validate_period_attributes(ann)
    assert fails == []


def test_dimension_validator_unknown_axis():
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="100",
        period_end="2024-12-31",
        dimensions={"regnskap-no:NotAnAxis": "regnskap-no:WhateverMember"},
    )
    fails = validate_dimension_members(ann)
    assert any(f.rule == "dimension" for f in fails)


def test_calc_arc_consistency_passes_when_sum_matches():
    """Eiendeler = Anleggsmidler + Omlopsmidler."""
    eiendeler = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="300",
        period_end="2024-12-31",
    )
    anlegg = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 20, 10, 30),
        concept_id="regnskap-no:Anleggsmidler", value_text="100",
        period_end="2024-12-31",
    )
    oml = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 40, 10, 50),
        concept_id="regnskap-no:Omlopsmidler", value_text="200",
        period_end="2024-12-31",
    )
    fails = validate_calc_arc_consistency([eiendeler, anlegg, oml])
    assert fails == {}


def test_calc_arc_consistency_fails_when_sum_mismatches():
    eiendeler = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="500",  # WRONG: should be 300
        period_end="2024-12-31",
    )
    anlegg = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 20, 10, 30),
        concept_id="regnskap-no:Anleggsmidler", value_text="100",
        period_end="2024-12-31",
    )
    oml = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 40, 10, 50),
        concept_id="regnskap-no:Omlopsmidler", value_text="200",
        period_end="2024-12-31",
    )
    fails = validate_calc_arc_consistency([eiendeler, anlegg, oml])
    assert eiendeler.id in fails
    f = fails[eiendeler.id][0]
    assert f.rule == "calc-arc"
    assert f.diff == pytest.approx(200.0, abs=1.0)


def test_validate_facts_end_to_end():
    eiendeler = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="300",
        period_end="2024-12-31",
    )
    anlegg = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 20, 10, 30),
        concept_id="regnskap-no:Anleggsmidler", value_text="100",
        period_end="2024-12-31",
    )
    oml = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 40, 10, 50),
        concept_id="regnskap-no:Omlopsmidler", value_text="200",
        period_end="2024-12-31",
    )
    report = validate_facts([eiendeler, anlegg, oml])
    assert report.conforms
    assert len(report.passing) == 3


def test_validate_facts_quarantines_bad_fact():
    eiendeler = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="500",  # WRONG
        period_end="2024-12-31",
    )
    anlegg = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 20, 10, 30),
        concept_id="regnskap-no:Anleggsmidler", value_text="100",
        period_end="2024-12-31",
    )
    oml = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 40, 10, 50),
        concept_id="regnskap-no:Omlopsmidler", value_text="200",
        period_end="2024-12-31",
    )
    report = validate_facts([eiendeler, anlegg, oml])
    assert not report.conforms
    assert len(report.failing) == 1
    failing_ann, fails = report.failing[0]
    assert failing_ann.id == eiendeler.id
    assert any(f.rule == "calc-arc" for f in fails)
