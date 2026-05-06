"""Tests for regnskapsnoter-xbrl.

Audit C6 closed: emits Inline XBRL 1.1 from regnskap-no facts.
"""
from __future__ import annotations

import pytest
from lxml import etree

from regnskapsnoter_xbrl import IxbrlFact, build_ixbrl


NS = {
    "xhtml": "http://www.w3.org/1999/xhtml",
    "ix": "http://www.xbrl.org/2013/inlineXBRL",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
}


def _parse(xhtml: bytes):
    """Parse the emitted document for assertions."""
    return etree.fromstring(xhtml)


def _balance_facts():
    return [
        IxbrlFact(concept_id="regnskap-no:Eiendeler", value=300_000,
                   period_end="2024-12-31"),
        IxbrlFact(concept_id="regnskap-no:Anleggsmidler", value=100_000,
                   period_end="2024-12-31"),
        IxbrlFact(concept_id="regnskap-no:Omlopsmidler", value=200_000,
                   period_end="2024-12-31"),
    ]


# ---- Document shape ----

class TestDocumentShape:
    def test_returns_bytes(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        assert isinstance(out, bytes)
        assert out.startswith(b"<?xml")

    def test_root_is_xhtml_html(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        assert root.tag == f"{{{NS['xhtml']}}}html"

    def test_has_required_namespaces(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        nsmap = root.nsmap
        for prefix in ("ix", "xbrli", "iso4217", "link", "xlink"):
            assert prefix in nsmap, f"missing namespace: {prefix}"

    def test_has_ix_header(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        header = root.find(f".//{{{NS['ix']}}}header")
        assert header is not None

    def test_schema_ref_is_present(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        schema = root.find(f".//{{{NS['link']}}}schemaRef")
        assert schema is not None
        assert schema.get(f"{{{NS['xlink']}}}href") is not None


# ---- Contexts ----

class TestContexts:
    def test_balance_facts_get_instant_context(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        contexts = root.findall(f".//{{{NS['xbrli']}}}context")
        # All 3 facts are balance items → one shared instant context
        assert len(contexts) == 1
        ctx = contexts[0]
        instant = ctx.find(f".//{{{NS['xbrli']}}}instant")
        assert instant is not None
        assert instant.text == "2024-12-31"

    def test_pl_facts_get_duration_context(self):
        # Aarsresultat (P&L) is a duration concept
        facts = [
            IxbrlFact(concept_id="regnskap-no:Aarsresultat", value=14_780,
                       period_end="2024-12-31"),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        ctx = root.find(f".//{{{NS['xbrli']}}}context")
        sd = ctx.find(f".//{{{NS['xbrli']}}}startDate")
        ed = ctx.find(f".//{{{NS['xbrli']}}}endDate")
        assert sd is not None and sd.text == "2024-01-01"
        assert ed is not None and ed.text == "2024-12-31"

    def test_mixed_balance_and_pl_get_two_contexts(self):
        facts = _balance_facts() + [
            IxbrlFact(concept_id="regnskap-no:Aarsresultat", value=14_780,
                       period_end="2024-12-31"),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        contexts = root.findall(f".//{{{NS['xbrli']}}}context")
        # 1 instant (balance) + 1 duration (P&L)
        assert len(contexts) == 2

    def test_entity_identifier(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        ident = root.find(f".//{{{NS['xbrli']}}}identifier")
        assert ident is not None
        assert ident.text == "811602892"
        assert ident.get("scheme") == "https://www.brreg.no/"


# ---- Units ----

class TestUnits:
    def test_nok_unit_emitted(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        unit = root.find(f".//{{{NS['xbrli']}}}unit")
        assert unit is not None
        measure = unit.find(f".//{{{NS['xbrli']}}}measure")
        assert measure.text == "iso4217:NOK"

    def test_unit_id_referenced_by_facts(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        unit = root.find(f".//{{{NS['xbrli']}}}unit")
        unit_id = unit.get("id")
        # Each ix:nonFraction must reference this unit
        nfs = root.findall(f".//{{{NS['ix']}}}nonFraction")
        assert len(nfs) >= 1
        for nf in nfs:
            assert nf.get("unitRef") == unit_id


# ---- Facts ----

class TestFacts:
    def test_each_fact_becomes_nonfraction(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        nfs = root.findall(f".//{{{NS['ix']}}}nonFraction")
        names = sorted(nf.get("name") for nf in nfs)
        assert names == [
            "regnskap-no:Anleggsmidler",
            "regnskap-no:Eiendeler",
            "regnskap-no:Omlopsmidler",
        ]

    def test_numeric_value_is_serialised(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        eiendeler = root.xpath(
            f"//ix:nonFraction[@name='regnskap-no:Eiendeler']",
            namespaces=NS,
        )[0]
        assert eiendeler.text == "300000"

    def test_negative_value_uses_sign_attribute(self):
        facts = [
            IxbrlFact(concept_id="regnskap-no:Egenkapital", value=-90_488,
                       period_end="2024-12-31"),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        nf = root.find(f".//{{{NS['ix']}}}nonFraction")
        assert nf.get("sign") == "-"
        # Value text is the absolute value (the sign attribute carries the sign)
        assert nf.text == "90488"

    def test_decimals_attribute_set(self):
        facts = [
            IxbrlFact(concept_id="regnskap-no:Eiendeler", value=300,
                       period_end="2024-12-31", decimals=-3),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        nf = root.find(f".//{{{NS['ix']}}}nonFraction")
        assert nf.get("decimals") == "-3"

    def test_text_value_uses_nonnumeric(self):
        facts = [
            IxbrlFact(concept_id="regnskap-no:RegnskapsregelText",
                       value="Regnskapslovens alminnelige regler",
                       period_end="2024-12-31"),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        nn = root.find(f".//{{{NS['ix']}}}nonNumeric")
        assert nn is not None
        assert nn.text == "Regnskapslovens alminnelige regler"

    def test_facts_reference_correct_context(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        ctx_id = root.find(f".//{{{NS['xbrli']}}}context").get("id")
        nfs = root.findall(f".//{{{NS['ix']}}}nonFraction")
        for nf in nfs:
            assert nf.get("contextRef") == ctx_id


# ---- Period inference ----

class TestPeriodInference:
    def test_explicit_period_type_overrides_inference(self):
        facts = [
            IxbrlFact(
                concept_id="regnskap-no:Eiendeler",
                value=300_000,
                period_end="2024-12-31",
                period_type="duration",   # override
            ),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        ctx = root.find(f".//{{{NS['xbrli']}}}context")
        # Override forces duration context (startDate/endDate, not instant)
        assert ctx.find(f".//{{{NS['xbrli']}}}startDate") is not None
        assert ctx.find(f".//{{{NS['xbrli']}}}instant") is None

    def test_unknown_concept_falls_back_to_duration(self):
        """A concept not in the taxonomy defaults to duration."""
        facts = [
            IxbrlFact(concept_id="regnskap-no:NotInTaxonomy", value=42,
                       period_end="2024-12-31"),
        ]
        out = build_ixbrl(facts, entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        ctx = root.find(f".//{{{NS['xbrli']}}}context")
        assert ctx.find(f".//{{{NS['xbrli']}}}startDate") is not None


# ---- Validation: no orphan unit / context references ----

class TestReferentialIntegrity:
    def test_every_factrefs_an_existing_context(self):
        out = build_ixbrl(_balance_facts() + [
            IxbrlFact(concept_id="regnskap-no:Aarsresultat", value=14_780,
                       period_end="2024-12-31"),
        ], entity_orgnr="811602892",
            period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        ctx_ids = {c.get("id") for c in root.findall(f".//{{{NS['xbrli']}}}context")}
        for nf in root.findall(f".//{{{NS['ix']}}}nonFraction"):
            assert nf.get("contextRef") in ctx_ids

    def test_every_fact_refs_an_existing_unit(self):
        out = build_ixbrl(_balance_facts(), entity_orgnr="811602892",
                          period_start="2024-01-01", period_end="2024-12-31")
        root = _parse(out)
        unit_ids = {u.get("id") for u in root.findall(f".//{{{NS['xbrli']}}}unit")}
        for nf in root.findall(f".//{{{NS['ix']}}}nonFraction"):
            assert nf.get("unitRef") in unit_ids


def test_concept_id_without_prefix_raises():
    facts = [
        IxbrlFact(concept_id="Eiendeler", value=100,
                   period_end="2024-12-31"),
    ]
    with pytest.raises(ValueError, match="missing prefix"):
        build_ixbrl(facts, entity_orgnr="811602892",
                    period_start="2024-01-01", period_end="2024-12-31")
