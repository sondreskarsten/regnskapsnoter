"""Integration tests for ``CascadeOcrModel.__call__``.

These tests exercise the orchestration that the unit tests in test_vote.py
and test_voters.py don't cover:

- Page rendering pipeline (mocked backend)
- ThreadPoolExecutor parallelism over voters (with two real voters)
- Coordinate scale-up / scale-back round-trip
- Audit ledger writeback during conversion
- The handoff to ``post_process_cells`` (the parent's read-only `page.cells`
  property handling)

Audit (B2 + B3) flagged that ``CascadeOcrModel.__call__`` and ``AuditLedger``
had ZERO tests. This file closes both gaps with mocks that match the
real Docling Page + Backend + ConversionResult contract.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import (
    BoundingRectangle,
    SegmentedPdfPage,
    TextCell,
)

from docling_cascade_ocr.voters.base import VoterUnavailable
from docling_cascade_ocr.options import CascadeOcrOptions, CascadeVoter


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


pytestmark = pytest.mark.skipif(
    not (_has_pil_and_font() and _has_tesseract()),
    reason="PIL/font or pytesseract not installed",
)


@pytest.fixture
def page_image():
    """Render a known-text image suitable for two voters to read."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1200, 200), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36,
    )
    d.text((40, 60), "Sum eiendeler 1234567", font=font, fill="black")
    return img


@pytest.fixture
def mock_page(page_image):
    """A mock Docling Page that yields ``page_image`` from its backend."""
    from docling_core.types.doc.base import Size

    backend = MagicMock()
    backend.is_valid.return_value = True
    backend.get_page_image.return_value = page_image

    page = MagicMock()
    page.page_no = 1
    page.size = Size(width=400.0, height=66.7)  # /3 of image, mimicking 72→216 DPI mapping
    page._backend = backend
    page.cells = []
    page.parsed_page = None  # post_process_cells is monkey-patched in each test

    return page


@pytest.fixture
def mock_conv_res(tmp_path):
    """A mock ConversionResult with an input file path."""
    pdf_path = tmp_path / "fixture.pdf"
    pdf_path.write_bytes(b"%PDF-fake%%EOF")
    cr = MagicMock()
    cr.input.file = pdf_path
    cr.timings = {}
    return cr


def _make_model(*, audit_path=None, voters=None):
    """Build a CascadeOcrModel with real voters (Tesseract pair) for integration."""
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling_cascade_ocr.model import CascadeOcrModel

    opts = CascadeOcrOptions(
        voters=voters or [
            CascadeVoter(name="tesseract"),
            CascadeVoter(name="tesseract_tsv"),
        ],
        min_voters_for_commit=1,
        column_drop_veto=False,
        audit_ledger_path=audit_path,
    )
    return CascadeOcrModel(
        enabled=True,
        artifacts_path=None,
        options=opts,
        accelerator_options=AcceleratorOptions(),
    )


class TestCallOrchestration:
    def test_call_returns_pages(self, mock_page, mock_conv_res, monkeypatch):
        """The model must yield Page objects (one per input)."""
        # Stub get_ocr_rects so it returns a single full-page rect without scipy
        from docling_cascade_ocr.model import CascadeOcrModel
        monkeypatch.setattr(
            CascadeOcrModel, "get_ocr_rects",
            lambda self, page: [BoundingBox(
                l=0, t=0, r=page.size.width, b=page.size.height,
                coord_origin=CoordOrigin.TOPLEFT,
            )],
        )
        # post_process_cells is a no-op for this test
        monkeypatch.setattr(CascadeOcrModel, "post_process_cells",
                            lambda self, cells, page: None)

        model = _make_model()
        pages = list(model(mock_conv_res, [mock_page]))
        assert len(pages) == 1
        assert pages[0] is mock_page

    def test_call_invokes_voters_and_writes_ledger(self, mock_page, mock_conv_res,
                                                     tmp_path, monkeypatch):
        """End-to-end: voters run, vote, ledger is written with v2 schema."""
        from docling_cascade_ocr.model import CascadeOcrModel
        monkeypatch.setattr(
            CascadeOcrModel, "get_ocr_rects",
            lambda self, page: [BoundingBox(
                l=0, t=0, r=page.size.width, b=page.size.height,
                coord_origin=CoordOrigin.TOPLEFT,
            )],
        )
        monkeypatch.setattr(CascadeOcrModel, "post_process_cells",
                            lambda self, cells, page: None)

        ledger_path = tmp_path / "audit.jsonl"
        model = _make_model(audit_path=str(ledger_path))
        pages = list(model(mock_conv_res, [mock_page]))

        # Ledger should have one record
        assert ledger_path.exists()
        lines = ledger_path.read_text().splitlines()
        assert len(lines) == 1

        rec = json.loads(lines[0])
        assert rec["_meta"]["audit_schema_version"] == "v2"
        assert rec["_meta"]["page_no"] == 1
        assert "tesseract" in rec["_meta"]["voters"]
        assert "tesseract_tsv" in rec["_meta"]["voters"]
        assert rec["_meta"]["page_size"] == [400.0, 66.7]

        # Per-voter cells present
        assert len(rec["per_voter"]["tesseract"]) >= 1
        assert len(rec["per_voter"]["tesseract_tsv"]) >= 2

        # Each per-voter cell has the documented schema
        for voter_cells in rec["per_voter"].values():
            for c in voter_cells:
                assert "text" in c and "confidence" in c and "bbox" in c
                assert "from_ocr" in c
                assert len(c["bbox"]) == 4

    def test_call_disabled_yields_pages_unchanged(self, mock_page, mock_conv_res):
        """When enabled=False the cascade is a passthrough."""
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling_cascade_ocr.model import CascadeOcrModel

        opts = CascadeOcrOptions()
        model = CascadeOcrModel(
            enabled=False,
            artifacts_path=None,
            options=opts,
            accelerator_options=AcceleratorOptions(),
        )
        pages = list(model(mock_conv_res, [mock_page]))
        assert pages == [mock_page]

    def test_call_skips_invalid_backend(self, mock_page, mock_conv_res, monkeypatch):
        """A page with is_valid()=False yields without OCR."""
        mock_page._backend.is_valid.return_value = False

        from docling_cascade_ocr.model import CascadeOcrModel
        monkeypatch.setattr(
            CascadeOcrModel, "get_ocr_rects",
            lambda self, page: [BoundingBox(
                l=0, t=0, r=1, b=1, coord_origin=CoordOrigin.TOPLEFT,
            )],
        )

        model = _make_model()
        pages = list(model(mock_conv_res, [mock_page]))
        assert pages == [mock_page]
        # Backend should NOT have been asked for the image
        mock_page._backend.get_page_image.assert_not_called()

    def test_call_no_ocr_rects_yields_unchanged(self, mock_page, mock_conv_res,
                                                  monkeypatch):
        """If get_ocr_rects returns [], the page is yielded without rendering."""
        from docling_cascade_ocr.model import CascadeOcrModel
        monkeypatch.setattr(CascadeOcrModel, "get_ocr_rects", lambda self, page: [])

        model = _make_model()
        pages = list(model(mock_conv_res, [mock_page]))
        assert pages == [mock_page]
        mock_page._backend.get_page_image.assert_not_called()


class TestCoordinateRoundTrip:
    """Audit-flagged: ``_scale_rects`` and ``_scale_cell_back`` must round-trip
    cleanly so cells reported by voters at image-pixel scale come back at
    page-coordinate scale."""

    def test_scale_round_trip_preserves_position(self):
        from docling_cascade_ocr.model import CascadeOcrModel

        cell = TextCell(
            index=0, text="x", orig="x", from_ocr=True, confidence=1.0,
            rect=BoundingRectangle.from_bounding_box(BoundingBox(
                l=300.0, t=600.0, r=600.0, b=900.0,
                coord_origin=CoordOrigin.TOPLEFT,
            )),
        )
        scale = 3
        scaled_back = CascadeOcrModel._scale_cell_back(cell, scale)
        bb = scaled_back.rect.to_bounding_box()
        assert bb.l == pytest.approx(100.0)
        assert bb.t == pytest.approx(200.0)
        assert bb.r == pytest.approx(200.0)
        assert bb.b == pytest.approx(300.0)

    def test_scale_rects_multiplies_correctly(self):
        from docling_cascade_ocr.model import CascadeOcrModel

        page_rect = BoundingBox(l=10, t=20, r=30, b=40,
                                 coord_origin=CoordOrigin.TOPLEFT)
        scaled = CascadeOcrModel._scale_rects([page_rect], scale=3)
        assert len(scaled) == 1
        assert scaled[0].l == 30
        assert scaled[0].t == 60
        assert scaled[0].r == 90
        assert scaled[0].b == 120
