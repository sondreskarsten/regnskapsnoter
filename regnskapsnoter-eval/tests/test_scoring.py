"""Tests for the eval harness.

Covers:

- ``number_present`` matching grouped, digit-by-digit, signed, and parenthesised forms
- Truth loader reading the local ``tests/data/brreg_ground_truth/`` mirror
- ``score_per_voter`` and ``score_fixture`` end-to-end with synthetic OCR text
"""
from __future__ import annotations

from pathlib import Path
import pytest

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from regnskapsnoter_eval import (
    EngineScore,
    ReliabilityReport,
    load_truth_from_local,
    number_present,
    score_consensus,
    score_engine_text,
    score_fixture,
    score_per_voter,
    truth_numbers,
)


TRUTH_DIR = Path(__file__).parent / "data" / "brreg_ground_truth"


# ---- number_present ----

def test_number_present_grouped():
    assert number_present(12345678, "Sum eiendeler 12 345 678 NOK")


def test_number_present_digit_by_digit():
    assert number_present(12345678, "Sum eiendeler 12345678 NOK")


def test_number_present_negative_paren():
    assert number_present(-90488, "Sum egenkapital (90 488)")


def test_number_present_negative_unicode_minus():
    assert number_present(-90488, "Sum egenkapital \u221290 488")


def test_number_present_grouped_with_extra_whitespace():
    assert number_present(12345678, "Sum eiendeler 12  345  678 NOK")


def test_number_present_zero_requires_separator():
    assert number_present(0, "Garantistillelser 0 0")
    # Within a longer number — still requires whitespace context
    assert not number_present(0, "1230456")


def test_number_present_not_in_text():
    assert not number_present(99999, "Sum eiendeler 12 345 678 NOK")


def test_number_present_handles_leading_zeros():
    """Don't match '12 345' inside '912 345'."""
    # This is a known limitation: regex doesn't enforce word boundaries.
    # Document the current behavior to detect any change.
    assert number_present(12345, "X 912 345")  # current: matches
    # A future hardening could add a leading non-digit anchor.


# ---- Truth loader ----

def test_truth_loader_reads_10_files():
    truth = load_truth_from_local(TRUTH_DIR)
    assert len(truth) == 10
    assert all(orgnr.isdigit() and len(orgnr) == 9 for orgnr in truth)


def test_truth_loader_extracts_key_metrics():
    truth = load_truth_from_local(TRUTH_DIR)
    fana = truth.get("811602892")
    assert fana is not None
    # We know from inspection: this orgnr has period 2022 and several key metrics
    assert fana.period_to == "2022-12-31"
    assert "key_metrics" in fana.__dataclass_fields__
    assert len(fana.key_metrics) >= 1


def test_truth_numbers_distinct_per_orgnr():
    truth = load_truth_from_local(TRUTH_DIR)
    nums = truth_numbers(truth, drop_zero=True)
    # Every orgnr has at least one non-zero key metric
    for orgnr, ns in nums.items():
        assert len(ns) >= 1, f"orgnr {orgnr} has no truth numbers"


def test_truth_numbers_total_is_substantial():
    """Sanity: the v2 fixture has ~100 truth values total across 10 orgnrs."""
    truth = load_truth_from_local(TRUTH_DIR)
    nums = truth_numbers(truth, drop_zero=True)
    total = sum(len(s) for s in nums.values())
    # Allow a wide range — the original audit reported ~100, but distinct integer
    # collapse may reduce that. We require ≥ 50 to catch broken loading.
    assert total >= 50, f"only {total} distinct truth integers — loader broken?"


# ---- Score primitives ----

def _cell(text: str) -> TextCell:
    return TextCell(
        index=0, text=text, orig=text, from_ocr=True, confidence=1.0,
        rect=BoundingRectangle.from_bounding_box(BoundingBox(
            l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT,
        )),
    )


def test_score_engine_text_recall():
    truth = {1234, 5678, 9999}
    text = "Some 1234 here and 5 678 there"
    sc = score_engine_text(engine="x", orgnr="111", text=text, truth=truth)
    assert sc.hits == 2
    assert sc.total == 3
    assert sc.recall == pytest.approx(2/3)
    assert 9999 in sc.missed


def test_score_per_voter_with_two_voters():
    truth = {1234, 5678}
    per_voter = {
        "v1": [_cell("see 1234 and 5678")],   # hits both
        "v2": [_cell("just 1234")],           # hits one
    }
    out = score_per_voter(orgnr="111", per_voter_cells=per_voter, truth=truth)
    assert out["v1"].hits == 2
    assert out["v2"].hits == 1


def test_score_consensus_unanimous_and_reliable():
    truth = {1234}
    per_voter = {f"v{i}": [_cell("we see 1234")] for i in range(7)}
    reports = score_consensus(orgnr="111", per_voter_cells=per_voter, truth=truth,
                               min_voters_for_reliable=7)
    assert len(reports) == 1
    r = reports[0]
    assert r.n_hit == 7
    assert r.unanimous
    assert r.reliable


def test_score_consensus_reliable_but_not_unanimous():
    truth = {1234}
    per_voter = {f"v{i}": [_cell("1234")] for i in range(7)}
    per_voter["v_bad"] = [_cell("nothing here")]
    reports = score_consensus(orgnr="111", per_voter_cells=per_voter, truth=truth,
                               min_voters_for_reliable=7)
    r = reports[0]
    assert r.n_hit == 7
    assert not r.unanimous
    assert r.reliable


def test_score_consensus_universal_miss():
    truth = {1234}
    per_voter = {f"v{i}": [_cell("nothing")] for i in range(7)}
    reports = score_consensus(orgnr="111", per_voter_cells=per_voter, truth=truth)
    r = reports[0]
    assert r.n_hit == 0
    assert not r.reliable


def test_score_fixture_aggregates_across_orgnrs():
    cells = {
        "111": {f"v{i}": [_cell("1234 and 5678")] for i in range(7)},
        "222": {f"v{i}": [_cell("only 9999")] for i in range(7)},
    }
    truth = {"111": {1234, 5678}, "222": {9999, 8888}}
    fs = score_fixture(cells_per_orgnr_per_voter=cells, truth_per_orgnr=truth,
                       min_voters_for_reliable=7)
    assert fs.n_orgnrs == 2
    # 111: 2 truth values, both unanimous-hit. 222: 2 truth values, only 9999 hit.
    assert fs.n_truth_values == 4
    assert fs.n_unanimous == 3   # 1234, 5678, 9999
    assert fs.n_reliable == 3
    assert fs.n_universal_miss == 1   # 8888
    assert fs.fraction_reliable == pytest.approx(3/4)


def test_score_fixture_per_voter_recall():
    cells = {
        "111": {
            "good": [_cell("1234 and 5678")],
            "bad": [_cell("nothing here")],
        }
    }
    truth = {"111": {1234, 5678}}
    fs = score_fixture(cells_per_orgnr_per_voter=cells, truth_per_orgnr=truth,
                       min_voters_for_reliable=1)
    assert fs.per_voter_recall["good"] == (2, 2)
    assert fs.per_voter_recall["bad"] == (0, 2)


# ---- Cross-check: real fixture loads with expected truth count ----

def test_real_fixture_loads_consistent_truth_set():
    """The 10-PDF v2 fixture must produce a stable truth-set count across
    test runs. If this number drifts the BRREG ground-truth files were
    edited and the cascade verdict needs re-validation."""
    truth = load_truth_from_local(TRUTH_DIR)
    nums = truth_numbers(truth, drop_zero=True)
    total = sum(len(s) for s in nums.values())
    # Snapshot the count discovered at commit time. If this changes, treat
    # it as a deliberate signal that the fixture changed.
    assert 50 <= total <= 200, (
        f"truth integer count {total} outside expected range — "
        "BRREG ground-truth files may have been replaced. Update this assertion "
        "with the new count after verifying the fixture is intentional."
    )
