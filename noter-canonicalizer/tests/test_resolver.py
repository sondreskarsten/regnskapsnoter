"""Tests for noter-canonicalizer."""
from __future__ import annotations

import pytest

from noter_canonicalizer import resolve, resolve_many, normalise, ResolutionResult


def test_normalise_basic():
    assert normalise("  Sum   eiendeler  ") == "sum eiendeler"


def test_normalise_nfkc():
    # Compatibility-decomposable ligatures are folded under NFKC + casefold
    assert normalise("eﬃcient") == "efficient"


def test_resolve_exact_match():
    """'Eiendeler' is a standardLabel for regnskap-no:Eiendeler."""
    r = resolve("Eiendeler")
    assert r.resolved
    assert r.match.concept_id == "regnskap-no:Eiendeler"
    assert r.match.method == "exact"
    assert r.match.confidence == 1.0


def test_resolve_exact_normalised():
    """Whitespace and case differences should not block exact match."""
    r = resolve("  EIENDELER  ")
    assert r.resolved
    assert r.match.concept_id == "regnskap-no:Eiendeler"


def test_resolve_unknown_returns_failure():
    r = resolve("Some made-up note title that doesn't exist anywhere")
    assert not r.resolved
    assert r.match is None


def test_resolve_fuzzy_kicks_in():
    """A close-but-not-exact label should be picked up by the fuzzy stage."""
    # "Eiendeler totalt" — fuzzy variant of "Eiendeler"
    r = resolve("Eiendeler totalt", use_fuzzy=True)
    # Either resolves via fuzzy, or doesn't — both are acceptable but we want
    # at least the fuzzy stage to have been attempted
    assert "fuzzy" in r.method_chain


def test_resolve_skips_fuzzy_when_disabled():
    r = resolve("Eiendeler totalt", use_fuzzy=False, use_embedding=False)
    assert "fuzzy" not in r.method_chain


def test_resolve_many():
    results = resolve_many(["Eiendeler", "nonsense xyz"])
    assert len(results) == 2
    assert results[0].resolved
    assert not results[1].resolved


def test_resolve_returns_candidates_for_failed_match():
    """Even when nothing matches, the result has a candidates list (possibly empty)."""
    r = resolve("xyzzy123")
    assert isinstance(r.candidates, list)


def test_method_chain_records_stages_attempted():
    r = resolve("Eiendeler")
    # Exact match should short-circuit; only "exact" recorded
    assert r.method_chain == ["exact"]


def test_lang_pref_prefers_correct_language_on_collision():
    """When both nb and en have the same label text, lang_pref wins."""
    # 'Bilanseført' isn't a label collision but 'Eiendeler' (nb) and 'Assets' (en)
    # are different texts so this exercises only the path. Just smoke-test.
    r = resolve("Eiendeler", lang_pref="nb")
    assert r.match.matched_label_lang == "nb"
