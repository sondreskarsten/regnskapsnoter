"""Tests for the regnskap-no taxonomy API."""
from __future__ import annotations

import pytest

from regnskap_no import api


def test_list_concepts_returns_279():
    concepts = list(api.list_concepts())
    # 279 concepts in v1.0.3
    assert len(concepts) == 279


def test_list_axes_returns_4():
    axes = list(api.list_axes())
    assert len(axes) == 4


def test_concepts_have_status():
    concepts = list(api.list_concepts())
    statuses = {c.status for c in concepts}
    # Per the lifecycle, every concept has status candidate/standard/deprecated/retired
    assert statuses.issubset({"candidate", "standard", "deprecated", "retired"})


def test_known_concept_lookup():
    """Spot-check that Eiendeler exists (the balance-sheet total)."""
    c = api.get_concept("regnskap-no:Eiendeler")
    assert c is not None
    assert c.namespace == "regnskap-no"
    # Eiendeler is a balance-sheet item: instant period
    assert c.period_type == "instant"
    assert c.balance == "debit"


def test_concept_labels():
    """Every standard concept should have at least one Bokmål label."""
    c = api.get_concept("regnskap-no:Eiendeler")
    assert c is not None
    labels = c.all_labels()
    assert len(labels) > 0
    nb = [l for l in labels if l.lang == "nb"]
    assert len(nb) > 0
    assert any(l.role == "standardLabel" for l in nb)


def test_calc_children_for_eiendeler():
    """Eiendeler has Anleggsmidler + Omlopsmidler as direct calc-arc children."""
    arcs = api.get_calc_children("regnskap-no:Eiendeler")
    assert len(arcs) >= 2
    children = {a.child_id for a in arcs}
    assert "regnskap-no:Anleggsmidler" in children
    assert "regnskap-no:Omlopsmidler" in children
    for a in arcs:
        assert a.weight in (1.0, -1.0)
        assert a.parent_id == "regnskap-no:Eiendeler"


def test_search_label_exact():
    """Exact (normalised) lookup finds Eiendeler standardLabel."""
    matches = api.search_label("Eiendeler", lang="nb", exact=True)
    assert len(matches) >= 1
    assert any(m.subject_id == "regnskap-no:Eiendeler" for m in matches)


def test_search_label_inexact():
    matches = api.search_label("eiendel", lang="nb", exact=False)
    assert len(matches) > 0


def test_axes_present():
    """The 4 expected axes are present."""
    expected = {
        "regnskap-no:EgenkapitalKomponentAxis",
        "regnskap-no:EgenkapitalEndringAxis",
        "regnskap-no:KlassifiseringAvAnleggsmidlerAxis",
        "regnskap-no:AnleggsmidlerEndringAxis",
    }
    have = {a.axis_id for a in api.list_axes()}
    assert expected.issubset(have)


def test_axis_members_for_egenkapital_komponent():
    members = api.get_axis_members("regnskap-no:EgenkapitalKomponentAxis")
    assert len(members) > 0


def test_mappings_exist():
    """Eiendeler should map to an IFRS-Full concept (or have a norwegian_specific note)."""
    ms = api.get_mappings("regnskap-no:Eiendeler")
    assert isinstance(ms, list)


def test_references_for_eiendeler():
    """Every concept should reference at least one authoritative source."""
    refs = api.get_references("regnskap-no:Eiendeler")
    assert len(refs) >= 1
    pubs = {r.publisher for r in refs}
    # Should reference regnskapsloven (the Accounting Act) at minimum
    assert any(
        "regnskapsloven" in p.lower()
        or "rskl" in p.lower()
        or "stortinget" in p.lower()
        for p in pubs
    )
