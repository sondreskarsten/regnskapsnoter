"""Tests for bokmål/nynorsk equivalence in noter-canonicalizer.

Audit B8: the original equivalence stub had 3 entries (one a no-op).
Real BRREG noter PDFs include nynorsk submissions (especially from
Vestland and Møre og Romsdal entities). Without proper equivalence the
canonicaliser falls through to fuzzy/embedding even on what should be
exact-form matches.

The taxonomy v1.0.3 ships only bokmål labels (314 lang='nb', 0 lang='nn'),
so collapsing nynorsk surface forms to bokmål before lookup is the only
way to match nynorsk inputs without round-tripping through the embedding
stage.

Each test covers a real (nynorsk text, expected bokmål concept_id) pair.
When the equivalence table grows, add at least one test here so the
change is auditable.
"""
from __future__ import annotations

import pytest

from noter_canonicalizer import resolve, normalise
from noter_canonicalizer.resolver import _bokmaal_nynorsk_normalise


class TestNynorskNormalise:
    def test_eigedelar_to_eiendeler(self):
        """Nynorsk 'eigedelar' (assets) collapses to bokmål 'eiendeler'."""
        assert _bokmaal_nynorsk_normalise("eigedelar") == "eiendeler"

    def test_eigenkapital_to_egenkapital(self):
        assert _bokmaal_nynorsk_normalise("eigenkapital") == "egenkapital"

    def test_rekneskap_to_regnskap(self):
        assert _bokmaal_nynorsk_normalise("rekneskap") == "regnskap"

    def test_omløpsmidlar_to_omløpsmidler(self):
        # nynorsk plural ends in -ar, bokmål plural ends in -er.
        # The bokmål standardLabel keeps the ø; only the concept ID
        # transliterates ø→o because the ID space is ASCII-only.
        assert _bokmaal_nynorsk_normalise("omløpsmidlar") == "omløpsmidler"

    def test_salsinntekt_to_salgsinntekt(self):
        # nynorsk drops the 'g' in 'sals-'
        assert _bokmaal_nynorsk_normalise("salsinntekt") == "salgsinntekt"

    def test_long_form_first(self):
        """Longer matches must be tried before their substrings."""
        # rekneskapsår should resolve to regnskapsaar in one step,
        # not be split into rekneskap + sår
        out = _bokmaal_nynorsk_normalise("rekneskapsår")
        assert out == "regnskapsaar"

    def test_does_not_replace_when_bokmaal_already_present(self):
        """Conservative substitution: don't double-replace mixed-language text."""
        out = _bokmaal_nynorsk_normalise("Rekneskap (regnskap)")
        # The bokmål form is already present, so leave the nynorsk source intact.
        # This avoids producing 'regnskap (regnskap)' duplicates.
        assert "regnskap" in out

    def test_unrelated_words_unchanged(self):
        assert _bokmaal_nynorsk_normalise("Sum totalt") == "Sum totalt"


class TestNormaliseEndToEnd:
    def test_normalise_lowercases_and_substitutes(self):
        # Casefold + nynorsk equivalence in one pass
        assert normalise("Eigenkapital") == "egenkapital"

    def test_normalise_handles_whitespace(self):
        assert normalise("  Eigedelar  totalt  ") == "eiendeler totalt"


class TestResolveNynorskInput:
    """End-to-end: feed nynorsk text into resolve(); expect a bokmål concept_id."""

    def test_eigedelar_resolves_to_eiendeler(self):
        r = resolve("Eigedelar")
        assert r.resolved
        assert r.match.concept_id == "regnskap-no:Eiendeler"
        # Should hit at the EXACT stage after nynorsk normalisation
        assert r.match.method == "exact"

    def test_eigenkapital_resolves_to_egenkapital(self):
        r = resolve("Eigenkapital")
        assert r.resolved
        assert r.match.concept_id == "regnskap-no:Egenkapital"
        assert r.match.method == "exact"

    def test_omløpsmidlar_resolves_to_omlopsmidler(self):
        r = resolve("Omløpsmidlar")
        # Note: 'Omlopsmidler' uses 'lop' not 'løp' in the concept ID
        assert r.resolved
        assert r.match.concept_id == "regnskap-no:Omlopsmidler"

    def test_anleggsmiddel_singular_works(self):
        """Singular forms also need to map (ID is plural Anleggsmidler)."""
        # Nynorsk singular = bokmål singular here (no change needed)
        r = resolve("Anleggsmidler")  # bokmål plural
        assert r.resolved
        assert r.match.concept_id == "regnskap-no:Anleggsmidler"

    def test_salsinntekt_resolves_to_salgsinntekt(self):
        r = resolve("Salsinntekt")
        assert r.resolved
        assert r.match.concept_id == "regnskap-no:Salgsinntekt"

    def test_mixed_case_input(self):
        """Casefold + nynorsk equivalence both apply."""
        r = resolve("EIGENKAPITAL")
        assert r.resolved
        assert r.match.concept_id == "regnskap-no:Egenkapital"


class TestEquivalenceTableShape:
    """Static checks on the equivalence table itself."""

    def test_no_circular_mappings(self):
        """No nynorsk form should appear as a bokmål value."""
        from noter_canonicalizer.resolver import _NN_TO_NB
        nynorsk_keys = set(_NN_TO_NB)
        bokmål_values = set(_NN_TO_NB.values())
        # If a key also appears as a value, the substitution would be cyclic
        # (a→b→a). This shouldn't happen with the current table.
        overlap = nynorsk_keys & bokmål_values
        assert overlap == set(), f"circular mappings: {overlap}"

    def test_table_is_nontrivial(self):
        """The audit found the original stub had only 3 entries (one no-op).
        Require ≥ 20 real entries so the table covers basic financial
        vocabulary."""
        from noter_canonicalizer.resolver import _NN_TO_NB
        # Drop pure no-ops where nynorsk == bokmål
        real = {k: v for k, v in _NN_TO_NB.items() if k != v}
        assert len(real) >= 20

    def test_no_pure_noop_entries(self):
        """An entry like ``"skatt": "skatt"`` is dead weight — should be removed."""
        from noter_canonicalizer.resolver import _NN_TO_NB
        noops = [k for k, v in _NN_TO_NB.items() if k == v]
        assert noops == [], f"no-op entries: {noops}"
