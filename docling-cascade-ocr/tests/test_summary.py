"""Tests for the per-document cascade summary (audit C9).

The audit flagged: "per-cell metadata is set; per-document roll-up is not."

These tests verify:

1. ``CascadeSummary.update_from_bbox`` correctly aggregates cluster-level
   diagnostics into n_clusters_total / committed / unanimous / minority.
2. ``CascadeSummary.update_from_token`` correctly aggregates token-level
   diagnostics into n_tokens_committed / unanimous.
3. The summary is reset on each new ``__call__`` and exposed via
   ``CascadeOcrModel.summary`` for downstream consumers.
4. ``to_dict()`` produces a JSON-serialisable mapping suitable for
   embedding in ``DoclingDocument.metadata``.
"""
from __future__ import annotations

import json

import pytest

from docling_cascade_ocr.summary import CascadeSummary


# ---- update_from_bbox ----

class TestUpdateFromBbox:
    def test_empty_diagnostics(self):
        s = CascadeSummary()
        s.update_from_bbox({}, threshold=7)
        assert s.n_clusters_total == 0
        assert s.n_clusters_unanimous == 0
        assert s.n_clusters_committed == 0
        assert s.n_clusters_minority == 0

    def test_unanimous_cluster_counted(self):
        s = CascadeSummary()
        s.update_from_bbox({
            "cluster:0": {
                "n_voters_hit": 7, "n_voters_attempted": 7,
                "column_dropped_voters": [],
            }
        }, threshold=7)
        assert s.n_clusters_total == 1
        assert s.n_clusters_unanimous == 1
        assert s.n_clusters_committed == 1
        assert s.n_clusters_minority == 0

    def test_minority_cluster_counted(self):
        s = CascadeSummary()
        s.update_from_bbox({
            "cluster:0": {
                "n_voters_hit": 3, "n_voters_attempted": 7,
                "column_dropped_voters": [],
            }
        }, threshold=7)
        assert s.n_clusters_total == 1
        assert s.n_clusters_committed == 0
        assert s.n_clusters_minority == 1
        assert s.n_clusters_unanimous == 0

    def test_committed_but_not_unanimous(self):
        """≥ threshold but not all voters: counts as committed, not unanimous."""
        s = CascadeSummary()
        s.update_from_bbox({
            "cluster:0": {
                "n_voters_hit": 7, "n_voters_attempted": 8,
                "column_dropped_voters": [],
            }
        }, threshold=7)
        assert s.n_clusters_committed == 1
        assert s.n_clusters_unanimous == 0
        assert s.n_clusters_minority == 0

    def test_column_dropped_voters_per_page(self):
        """A voter dropped on TWO pages should count 2."""
        s = CascadeSummary()
        s.update_from_bbox({
            "cluster:0": {
                "n_voters_hit": 6, "n_voters_attempted": 7,
                "column_dropped_voters": ["bad_voter"],
            }
        }, threshold=7)
        s.update_from_bbox({
            "cluster:0": {
                "n_voters_hit": 6, "n_voters_attempted": 7,
                "column_dropped_voters": ["bad_voter"],
            }
        }, threshold=7)
        assert s.voters_column_dropped_pages == {"bad_voter": 2}

    def test_column_dropped_dedups_within_page(self):
        """Multiple clusters on one page each report the same dropped voter
        — we count the page once."""
        s = CascadeSummary()
        s.update_from_bbox({
            "cluster:0": {"n_voters_hit": 6, "n_voters_attempted": 7,
                          "column_dropped_voters": ["bad"]},
            "cluster:1": {"n_voters_hit": 6, "n_voters_attempted": 7,
                          "column_dropped_voters": ["bad"]},
        }, threshold=7)
        assert s.voters_column_dropped_pages == {"bad": 1}

    def test_only_cluster_keys_counted(self):
        """Diagnostics dict may contain non-cluster keys; we ignore them."""
        s = CascadeSummary()
        s.update_from_bbox({
            "cluster:0": {"n_voters_hit": 7, "n_voters_attempted": 7,
                          "column_dropped_voters": []},
            "token:0": {"value": 12345, "unanimous": True,
                        "voters_hit": ["a", "b"]},
        }, threshold=7)
        # Only cluster:0 counts in bbox metrics
        assert s.n_clusters_total == 1


# ---- update_from_token ----

class TestUpdateFromToken:
    def test_empty(self):
        s = CascadeSummary()
        s.update_from_token({})
        assert s.n_tokens_committed == 0
        assert s.n_tokens_unanimous == 0

    def test_unanimous_token(self):
        s = CascadeSummary()
        s.update_from_token({
            "token:0": {"value": 12345, "unanimous": True,
                        "voters_hit": ["a", "b"]},
        })
        assert s.n_tokens_committed == 1
        assert s.n_tokens_unanimous == 1

    def test_committed_not_unanimous(self):
        s = CascadeSummary()
        s.update_from_token({
            "token:0": {"value": 12345, "unanimous": False,
                        "voters_hit": ["a", "b"]},
        })
        assert s.n_tokens_committed == 1
        assert s.n_tokens_unanimous == 0

    def test_only_token_keys_counted(self):
        s = CascadeSummary()
        s.update_from_token({
            "cluster:0": {"n_voters_hit": 7, "n_voters_attempted": 7,
                          "column_dropped_voters": []},
            "token:0": {"value": 1, "unanimous": True,
                        "voters_hit": ["a"]},
        })
        assert s.n_tokens_committed == 1
        assert s.n_tokens_unanimous == 1


# ---- Properties + serialisation ----

class TestSummaryProperties:
    def test_fractions_zero_with_no_pages(self):
        s = CascadeSummary()
        assert s.fraction_clusters_unanimous == 0.0
        assert s.fraction_clusters_committed == 0.0

    def test_fractions_correct(self):
        s = CascadeSummary()
        s.n_clusters_total = 100
        s.n_clusters_committed = 99
        s.n_clusters_unanimous = 81
        assert s.fraction_clusters_committed == 0.99
        assert s.fraction_clusters_unanimous == 0.81

    def test_to_dict_is_json_serialisable(self):
        s = CascadeSummary()
        s.n_pages = 6
        s.n_voters = 7
        s.voters_attempted = ["tesseract", "tesseract_tsv"]
        s.n_clusters_total = 47
        s.n_clusters_unanimous = 47
        s.n_clusters_committed = 47
        s.n_tokens_committed = 47
        s.n_tokens_unanimous = 47
        d = s.to_dict()
        # round-trip through json
        roundtrip = json.loads(json.dumps(d))
        assert roundtrip["n_pages"] == 6
        assert roundtrip["n_voters"] == 7
        assert roundtrip["voters_attempted"] == ["tesseract", "tesseract_tsv"]
        assert roundtrip["fraction_clusters_unanimous"] == 1.0


# ---- Integration with CascadeOcrModel ----

def _has_pil_and_font() -> bool:
    try:
        from PIL import ImageFont
        ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        return True
    except Exception:
        return False


def _has_tesseract() -> bool:
    try:
        import pytesseract  # noqa
        pytesseract.get_languages()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not (_has_pil_and_font() and _has_tesseract()),
    reason="PIL/font or pytesseract not installed",
)
class TestSummaryIntegration:
    """End-to-end: run the model against a synthetic page and verify the
    summary is populated correctly."""

    @pytest.fixture
    def page_image(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (1200, 200), "white")
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36,
        )
        d.text((40, 60), "Sum eiendeler 12 345 678", font=font, fill="black")
        return img

    def test_summary_is_populated_after_call(self, page_image, tmp_path):
        from unittest.mock import MagicMock
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import Page  # noqa: F401
        from docling_core.types.doc.base import Size
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_cascade_ocr.model import CascadeOcrModel
        from docling_cascade_ocr.options import CascadeOcrOptions, CascadeVoter

        # Build a model with two real voters (Tesseract pair)
        opts = CascadeOcrOptions(
            voters=[
                CascadeVoter(name="tesseract"),
                CascadeVoter(name="tesseract_tsv"),
            ],
            min_voters_for_commit=1,
            column_drop_veto=False,
        )
        model = CascadeOcrModel(
            enabled=True,
            artifacts_path=None,
            options=opts,
            accelerator_options=AcceleratorOptions(),
        )

        # Mock page + conv_res
        backend = MagicMock()
        backend.is_valid.return_value = True
        backend.get_page_image.return_value = page_image

        page = MagicMock()
        page.page_no = 1
        page.size = Size(width=400.0, height=66.7)
        page._backend = backend
        page.cells = []
        page.parsed_page = None

        pdf_path = tmp_path / "fixture.pdf"
        pdf_path.write_bytes(b"%PDF-fake%%EOF")
        cr = MagicMock()
        cr.input.file = pdf_path
        cr.timings = {}

        # Patch get_ocr_rects + post_process_cells
        import unittest.mock as um
        with um.patch.object(
            CascadeOcrModel, "get_ocr_rects",
            lambda self, p: [BoundingBox(
                l=0, t=0, r=p.size.width, b=p.size.height,
                coord_origin=CoordOrigin.TOPLEFT,
            )],
        ), um.patch.object(
            CascadeOcrModel, "post_process_cells",
            lambda self, cells, p: None,
        ):
            list(model(cr, [page]))

        s = model.summary
        assert s.n_pages == 1
        assert s.n_voters == 2
        assert s.voters_attempted == ["tesseract", "tesseract_tsv"]
        # Both bbox-vote and token-vote contribute since vote_mode='both' default
        assert s.n_clusters_total >= 1
        # The image contains the number 12345678 — token vote should commit it
        assert s.n_tokens_committed >= 1
        # JSON-serialisable
        json.dumps(s.to_dict())

    def test_summary_resets_between_calls(self, page_image, tmp_path):
        """A second call must reset n_pages back to 1 (not accumulate to 2)."""
        from unittest.mock import MagicMock
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling_core.types.doc.base import Size
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_cascade_ocr.model import CascadeOcrModel
        from docling_cascade_ocr.options import CascadeOcrOptions, CascadeVoter

        opts = CascadeOcrOptions(
            voters=[CascadeVoter(name="tesseract")],
            min_voters_for_commit=1,
            column_drop_veto=False,
        )
        model = CascadeOcrModel(
            enabled=True,
            artifacts_path=None,
            options=opts,
            accelerator_options=AcceleratorOptions(),
        )

        def _make_page():
            backend = MagicMock()
            backend.is_valid.return_value = True
            backend.get_page_image.return_value = page_image
            page = MagicMock()
            page.page_no = 1
            page.size = Size(width=400.0, height=66.7)
            page._backend = backend
            page.cells = []
            page.parsed_page = None
            return page

        pdf_path = tmp_path / "fixture.pdf"
        pdf_path.write_bytes(b"%PDF-fake%%EOF")
        cr = MagicMock()
        cr.input.file = pdf_path
        cr.timings = {}

        import unittest.mock as um
        with um.patch.object(
            CascadeOcrModel, "get_ocr_rects",
            lambda self, p: [BoundingBox(
                l=0, t=0, r=p.size.width, b=p.size.height,
                coord_origin=CoordOrigin.TOPLEFT,
            )],
        ), um.patch.object(
            CascadeOcrModel, "post_process_cells",
            lambda self, cells, p: None,
        ):
            list(model(cr, [_make_page()]))
            n_after_first = model.summary.n_pages
            list(model(cr, [_make_page()]))
            n_after_second = model.summary.n_pages

        assert n_after_first == 1
        assert n_after_second == 1, (
            f"summary did not reset between calls: n_pages={n_after_second}"
        )
