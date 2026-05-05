"""Tests for the voting algorithm.

These tests exercise ``vote.py`` directly with synthetic ``TextCell``s so they
don't require any OCR engine to be installed.
"""
from __future__ import annotations

import pytest

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from docling_cascade_ocr.vote import (
    bbox_iou,
    cluster_cells_across_voters,
    detect_column_drop,
    normalise_text,
    vote_cluster,
    xalign_vote,
)


def _cell(text: str, l: float, t: float, r: float, b: float, *, conf: float = 0.9) -> TextCell:
    return TextCell(
        index=0, text=text, orig=text, from_ocr=True, confidence=conf,
        rect=BoundingRectangle.from_bounding_box(BoundingBox(
            l=l, t=t, r=r, b=b, coord_origin=CoordOrigin.TOPLEFT,
        )),
    )


# -- normalise_text --

def test_normalise_collapses_whitespace_and_nfkc():
    assert normalise_text("  Sum   eiendeler  ") == "Sum eiendeler"


def test_normalise_hyphen_variants_to_ascii():
    # en-dash, em-dash, minus → ASCII hyphen
    assert normalise_text("\u2013123") == "-123"
    assert normalise_text("\u2014123") == "-123"
    assert normalise_text("\u2212123") == "-123"


def test_normalise_paren_negative():
    assert normalise_text("(123 456)") == "-123 456"


def test_normalise_empty():
    assert normalise_text("") == ""


# -- bbox_iou --

def test_bbox_iou_identical_is_one():
    a = BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT)
    assert bbox_iou(a, a) == pytest.approx(1.0)


def test_bbox_iou_disjoint_is_zero():
    a = BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT)
    b = BoundingBox(l=20, t=20, r=30, b=30, coord_origin=CoordOrigin.TOPLEFT)
    assert bbox_iou(a, b) == 0.0


def test_bbox_iou_partial_overlap():
    a = BoundingBox(l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT)
    b = BoundingBox(l=5, t=0, r=15, b=10, coord_origin=CoordOrigin.TOPLEFT)
    # Intersection = 5*10=50; union = 10*10 + 10*10 - 50 = 150
    assert bbox_iou(a, b) == pytest.approx(50 / 150)


# -- cluster_cells_across_voters --

def test_cluster_groups_same_region_across_voters():
    per_voter = {
        "v1": [_cell("Skatt", 0, 0, 10, 10)],
        "v2": [_cell("Skatt", 1, 1, 9, 9)],
        "v3": [_cell("Skatt", 0, 0, 10, 10)],
    }
    clusters = cluster_cells_across_voters(per_voter, iou_threshold=0.3)
    assert len(clusters) == 1
    assert set(clusters[0].keys()) == {"v1", "v2", "v3"}


def test_cluster_keeps_distinct_regions_separate():
    per_voter = {
        "v1": [_cell("Skatt", 0, 0, 10, 10), _cell("Sum", 100, 100, 110, 110)],
        "v2": [_cell("Skatt", 0, 0, 10, 10), _cell("Sum", 100, 100, 110, 110)],
    }
    clusters = cluster_cells_across_voters(per_voter, iou_threshold=0.3)
    assert len(clusters) == 2


# -- vote_cluster --

def test_vote_cluster_unanimous():
    cluster = {
        "v1": _cell("Sum eiendeler", 0, 0, 10, 10),
        "v2": _cell("Sum eiendeler", 0, 0, 10, 10),
        "v3": _cell("Sum eiendeler", 0, 0, 10, 10),
    }
    text, n, alts = vote_cluster(cluster)
    assert text == "Sum eiendeler"
    assert n == 3
    assert alts == []


def test_vote_cluster_majority():
    cluster = {
        "v1": _cell("123", 0, 0, 10, 10),
        "v2": _cell("123", 0, 0, 10, 10),
        "v3": _cell("128", 0, 0, 10, 10),
    }
    text, n, alts = vote_cluster(cluster)
    assert text == "123"
    assert n == 2
    assert len(alts) == 1
    assert alts[0][0] == "128"
    assert alts[0][1] == ["v3"]


def test_vote_cluster_normalises_before_voting():
    cluster = {
        "v1": _cell("Sum  eiendeler", 0, 0, 10, 10),
        "v2": _cell("Sum eiendeler", 0, 0, 10, 10),
    }
    text, n, _ = vote_cluster(cluster)
    assert text == "Sum eiendeler"
    assert n == 2


# -- detect_column_drop --

def test_no_columns_no_drop():
    per_voter = {"v1": [_cell("a", 0, 0, 10, 10)]}
    assert detect_column_drop(per_voter, page_width=1000.0) == []


def test_column_drop_detects_collapsed_voter():
    # Two voters see two columns at x=100 and x=500; one voter sees only one column at x=300
    page_w = 1000.0
    per_voter = {
        "v1": [_cell("a", 100, 0, 110, 10), _cell("b", 500, 0, 510, 10)],
        "v2": [_cell("a", 100, 0, 110, 10), _cell("b", 500, 0, 510, 10)],
        "v3": [_cell("a", 100, 0, 110, 10), _cell("b", 500, 0, 510, 10)],
        "v4": [_cell("ab", 300, 0, 310, 10)],
    }
    dropped = detect_column_drop(per_voter, page_width=page_w)
    assert dropped == ["v4"]


# -- xalign_vote end-to-end --

def test_xalign_vote_commits_when_threshold_met():
    per_voter = {
        f"v{i}": [_cell("Sum eiendeler", 0, 0, 10, 10), _cell("12 345", 50, 0, 70, 10)]
        for i in range(7)
    }
    consensus, diagnostics = xalign_vote(
        per_voter, page_size=(100.0, 100.0), min_voters_for_commit=7,
    )
    assert len(consensus) == 2
    texts = [c.text for c in consensus]
    assert "Sum eiendeler" in texts
    assert "12 345" in texts
    # Diagnostics include voter hits
    for k, d in diagnostics.items():
        assert d["n_voters_hit"] == 7


def test_xalign_vote_skips_below_threshold():
    per_voter = {
        f"v{i}": [_cell("Sum", 0, 0, 10, 10)] for i in range(3)
    }
    consensus, _ = xalign_vote(
        per_voter, page_size=(100.0, 100.0), min_voters_for_commit=7,
    )
    assert consensus == []


def test_xalign_vote_excludes_column_dropped_voter():
    # 3 good voters see two columns; one bad voter merges them.
    page_w = 1000.0
    good = lambda: [_cell("100", 100, 0, 110, 10), _cell("200", 500, 0, 510, 10)]
    bad = [_cell("100200", 300, 0, 310, 10)]
    per_voter = {f"good{i}": good() for i in range(3)}
    per_voter["bad"] = bad

    consensus, diagnostics = xalign_vote(
        per_voter, page_size=(page_w, 100.0),
        min_voters_for_commit=2,
        column_drop_veto=True,
    )
    # Column-drop voter must be excluded from voting; consensus uses 3 good voters
    for d in diagnostics.values():
        assert "bad" in d["column_dropped_voters"]
        assert "bad" not in d["voters_attempted"]
