"""Arelle validation of iXBRL output (plan item 2).

Runs the actual Arelle validator against an iXBRL document built from
verified taxonomy concepts. This is the spec-compliance gate — it
proves the output is not just structurally well-formed XML, but
iXBRL 1.1 that a real XBRL validator accepts.

Requires: pip install arelle-release
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from regnskapsnoter_xbrl import IxbrlFact, build_ixbrl


def _has_arelle() -> bool:
    try:
        from arelle import Cntlr  # noqa
        return True
    except ImportError:
        return False


def _xsd_path() -> Path:
    return Path(__file__).parents[2] / "regnskap-no" / "src" / "regnskap_no" / "data" / "regnskap-no.xsd"


pytestmark = pytest.mark.skipif(
    not _has_arelle(),
    reason="arelle-release not installed",
)


def _build_test_doc(schema_ref: str) -> bytes:
    """Build an iXBRL doc with 9 verified concepts — balance + P&L + negative."""
    from regnskap_no import api

    concept_ids = [
        "regnskap-no:Eiendeler", "regnskap-no:Anleggsmidler",
        "regnskap-no:Omlopsmidler", "regnskap-no:Egenkapital",
        "regnskap-no:KortsiktigGjeld", "regnskap-no:AnnenLangsiktigGjeld",
        "regnskap-no:Aarsresultat", "regnskap-no:SumDriftsinntekter",
        "regnskap-no:AnnenDriftskostnad",
    ]
    for cid in concept_ids:
        assert api.get_concept(cid) is not None, f"{cid} missing from taxonomy"

    return build_ixbrl(
        [
            IxbrlFact(concept_id="regnskap-no:Eiendeler", value=300_000,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:Anleggsmidler", value=100_000,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:Omlopsmidler", value=200_000,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:Egenkapital", value=250_000,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:KortsiktigGjeld", value=30_000,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:AnnenLangsiktigGjeld", value=20_000,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:Aarsresultat", value=14_780,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:SumDriftsinntekter", value=87_600,
                       period_end="2024-12-31"),
            IxbrlFact(concept_id="regnskap-no:AnnenDriftskostnad", value=-72_820,
                       period_end="2024-12-31"),
        ],
        entity_orgnr="811602892",
        period_start="2024-01-01",
        period_end="2024-12-31",
        schema_ref=schema_ref,
    )


def test_arelle_zero_errors_on_balanced_facts():
    """Arelle accepts the iXBRL document with zero errors."""
    from arelle import Cntlr

    xsd = _xsd_path()
    if not xsd.exists():
        pytest.skip("regnskap-no.xsd not generated yet")

    doc = _build_test_doc(schema_ref=f"file://{xsd}")

    with tempfile.NamedTemporaryFile(suffix=".xhtml", delete=False) as f:
        f.write(doc)
        ixbrl_path = f.name

    ctrl = Cntlr.Cntlr(logFileName="logToPrint")
    model = ctrl.modelManager.load(ixbrl_path)

    errors = list(model.errors) if model and hasattr(model, "errors") else ["load_failed"]
    assert len(errors) == 0, (
        f"Arelle reported {len(errors)} errors: {errors}. "
        "The iXBRL output is not spec-compliant."
    )
    ctrl.close()


def test_arelle_finds_all_nine_facts():
    from arelle import Cntlr

    xsd = _xsd_path()
    if not xsd.exists():
        pytest.skip("regnskap-no.xsd not generated yet")

    doc = _build_test_doc(schema_ref=f"file://{xsd}")
    with tempfile.NamedTemporaryFile(suffix=".xhtml", delete=False) as f:
        f.write(doc)
        ixbrl_path = f.name

    ctrl = Cntlr.Cntlr(logFileName="logToPrint")
    model = ctrl.modelManager.load(ixbrl_path)
    facts_found = list(model.facts) if model and hasattr(model, "facts") else []
    assert len(facts_found) == 9, (
        f"Expected 9 facts, Arelle found {len(facts_found)}"
    )
    ctrl.close()


def test_arelle_finds_both_contexts():
    """One instant (balance) + one duration (P&L)."""
    from arelle import Cntlr

    xsd = _xsd_path()
    if not xsd.exists():
        pytest.skip("regnskap-no.xsd not generated yet")

    doc = _build_test_doc(schema_ref=f"file://{xsd}")
    with tempfile.NamedTemporaryFile(suffix=".xhtml", delete=False) as f:
        f.write(doc)
        ixbrl_path = f.name

    ctrl = Cntlr.Cntlr(logFileName="logToPrint")
    model = ctrl.modelManager.load(ixbrl_path)
    contexts = model.contexts if model and hasattr(model, "contexts") else {}
    assert len(contexts) == 2
    ctrl.close()


def test_arelle_accepts_negative_sign_attribute():
    """The sign='-' attribute on AnnenDriftskostnad must be accepted."""
    from arelle import Cntlr

    xsd = _xsd_path()
    if not xsd.exists():
        pytest.skip("regnskap-no.xsd not generated yet")

    doc = _build_test_doc(schema_ref=f"file://{xsd}")
    with tempfile.NamedTemporaryFile(suffix=".xhtml", delete=False) as f:
        f.write(doc)
        ixbrl_path = f.name

    ctrl = Cntlr.Cntlr(logFileName="logToPrint")
    model = ctrl.modelManager.load(ixbrl_path)
    errors = list(model.errors) if model and hasattr(model, "errors") else []
    # No sign-related errors
    sign_errors = [e for e in errors if "sign" in str(e).lower()]
    assert len(sign_errors) == 0
    # The fact value should be -72820
    for f in model.facts:
        if "AnnenDriftskostnad" in str(f.qname):
            assert f.value == "-72820" or f.value == -72820
    ctrl.close()


def test_xsd_exists_and_has_279_elements():
    """The generated XSD must declare all 279 taxonomy concepts."""
    from lxml import etree
    xsd = _xsd_path()
    if not xsd.exists():
        pytest.skip("regnskap-no.xsd not generated yet")
    tree = etree.parse(str(xsd))
    elements = tree.findall(
        ".//{http://www.w3.org/2001/XMLSchema}element"
    )
    assert len(elements) == 279, (
        f"XSD has {len(elements)} elements, expected 279"
    )
