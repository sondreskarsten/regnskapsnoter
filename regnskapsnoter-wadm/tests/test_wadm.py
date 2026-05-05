"""Tests for the WADM emitter."""
from __future__ import annotations

import json
import tempfile
import pytest

from regnskapsnoter_wadm import (
    Annotation,
    annotation_to_jsonld,
    annotations_to_jsonld_collection,
    build_fact_annotation,
    make_pdf_target,
    write_jsonl,
)


def test_make_pdf_target_minimal():
    t = make_pdf_target(pdf_uri="gs://b/x.pdf", page_no=4)
    assert t.source == "gs://b/x.pdf"
    assert len(t.selector) == 1  # FragmentSelector only
    assert t.selector[0].type == "FragmentSelector"
    assert t.selector[0].value == "page=4"


def test_make_pdf_target_full():
    t = make_pdf_target(
        pdf_uri="gs://b/x.pdf", page_no=4,
        bbox=(245.0, 612.0, 363.0, 626.0),
        consensus_text="Sum eiendeler",
        text_prefix="...",
        text_suffix="  12 345 678",
    )
    assert len(t.selector) == 3
    types = {s.type for s in t.selector}
    assert types == {"FragmentSelector", "SvgSelector", "TextQuoteSelector"}


def test_build_fact_annotation_includes_taxonomy_fields():
    """When the concept exists in the taxonomy, period_type and balance are filled in."""
    ann = build_fact_annotation(
        pdf_uri="gs://brreg/123/aarsregnskap.pdf",
        page_no=4, bbox=(245, 612, 363, 626),
        concept_id="regnskap-no:Eiendeler",
        value_text="12345678",
        cascade_voters_hit=["ocrmypdf", "tesseract", "tesseract_tsv",
                            "paddleocr", "doctr", "easyocr", "pix2struct"],
        cascade_voters_total=7,
        period_end="2024-12-31",
    )
    assert ann.period_type == "instant"
    assert ann.balance == "debit"
    assert ann.cascade_confidence is not None
    assert ann.cascade_confidence.voters == 7
    assert ann.cascade_confidence.of == 7
    assert ann.cascade_confidence.text == "unanimous"
    assert ann.id.startswith("urn:regnskapsnoter:annotation:")


def test_build_fact_annotation_handles_unknown_concept():
    """Unknown concept IDs don't fail; they just yield ann.period_type=None."""
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf",
        page_no=1, bbox=(0, 0, 100, 100),
        concept_id="regnskap-no:NotARealConcept",
        value_text="42",
    )
    assert ann.period_type is None
    assert ann.balance is None


def test_annotation_to_jsonld_has_context():
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="100",
    )
    j = annotation_to_jsonld(ann)
    assert "@context" in j
    assert j["@context"][0] == "http://www.w3.org/ns/anno.jsonld"
    assert j["type"] == "Annotation"


def test_namespaced_extensions_serialise_with_aliases():
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(0, 0, 10, 10),
        concept_id="regnskap-no:Eiendeler", value_text="100",
        cascade_voters_hit=["v1", "v2", "v3"],
        cascade_voters_total=7,
        period_end="2024-12-31",
    )
    j = annotation_to_jsonld(ann)
    assert "registrum:cascadeConfidence" in j
    assert "registrum:periodType" in j
    assert "registrum:balance" in j
    assert "registrum:periodEnd" in j
    assert j["registrum:periodType"] == "instant"
    assert j["registrum:balance"] == "debit"


def test_collection_serialisation():
    anns = [
        build_fact_annotation(
            pdf_uri="gs://b/x.pdf", page_no=p, bbox=(0, 0, 10, 10),
            concept_id="regnskap-no:Eiendeler", value_text=str(p * 100),
        )
        for p in (1, 2, 3)
    ]
    coll = annotations_to_jsonld_collection(anns, label="Test collection")
    assert coll["type"] == "AnnotationCollection"
    assert coll["total"] == 3
    assert len(coll["first"]["items"]) == 3


def test_write_jsonl_round_trip():
    anns = [
        build_fact_annotation(
            pdf_uri="gs://b/x.pdf", page_no=p, bbox=(0, 0, 10, 10),
            concept_id="regnskap-no:Eiendeler", value_text=str(p * 100),
        )
        for p in (1, 2, 3)
    ]
    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False) as f:
        path = f.name
    n = write_jsonl(anns, path)
    assert n == 3
    with open(path) as f:
        lines = f.readlines()
    assert len(lines) == 3
    for line in lines:
        rec = json.loads(line)
        assert rec["type"] == "Annotation"
        assert rec["body"][0]["source"] == "regnskap-no:Eiendeler"


def test_target_selector_includes_svg_when_bbox_provided():
    ann = build_fact_annotation(
        pdf_uri="gs://b/x.pdf", page_no=1, bbox=(10, 20, 30, 40),
        concept_id="regnskap-no:Eiendeler", value_text="100",
    )
    j = annotation_to_jsonld(ann)
    selectors = j["target"]["selector"]
    svg = next(s for s in selectors if s["type"] == "SvgSelector")
    # bbox (10, 20, 30, 40) → rect x=10 y=20 width=20 height=20
    assert "x='10'" in svg["value"]
    assert "y='20'" in svg["value"]
    assert "width='20'" in svg["value"]
    assert "height='20'" in svg["value"]
