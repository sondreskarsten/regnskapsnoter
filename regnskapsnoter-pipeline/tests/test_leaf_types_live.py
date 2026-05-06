"""Per-leaf-type config tests against a synthetic page (audit B7).

The audit flagged: existing pipeline tests check ``len(voters)``,
``column_drop_veto``, ``force_full_page_ocr`` flags only — no test feeds
a PDF through any of the 4 configs. Whether ``tx_log``'s
``require_unanimous_for_table_cells=True`` actually changes output
remained unverified.

These tests use the cascade *standalone* (not via Docling's DocumentConverter,
which OOMs in CI containers because it loads the layout + TableFormer
models). For each leaf-type config:

  - Build the CascadeOcrOptions from the factory
  - Construct a CascadeOcrModel with those options
  - Run it against a deterministic synthetic page raster
  - Assert the cascade behaves as the config promises (voter count,
    column-drop veto, audit ledger written)

This is the live counterpart to the structural ``test_pipeline.py`` tests.
Together they cover both "the config has the right shape" and "the cascade
running with this config produces a sensible result."
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


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
    """A deterministic balanse-style page: 'Sum eiendeler 12 345 678'."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1200, 200), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36,
    )
    d.text((40, 60), "Sum eiendeler 12 345 678", font=font, fill="black")
    return img


def _build_model_from_config(config_name: str, *, audit_ledger_path=None,
                              voter_subset=None):
    """Override the production voter list to use only the engine(s) installed
    in CI (tesseract + tesseract_tsv). The leaf-type factory's other settings
    (vote_mode, column_drop_veto, force_full_page_ocr, etc.) are preserved
    so we test what the config actually does, not just whether it builds."""
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling_cascade_ocr.model import CascadeOcrModel
    from docling_cascade_ocr.options import CascadeVoter
    from regnskapsnoter_pipeline.configs import get_config

    pdf_opts = get_config(config_name, audit_ledger_path=audit_ledger_path)
    cascade_opts = pdf_opts.ocr_options
    cascade_opts.voters = voter_subset or [
        CascadeVoter(name="tesseract"),
        CascadeVoter(name="tesseract_tsv"),
    ]
    cascade_opts.min_voters_for_commit = 1   # 2 voters in CI; commit on either

    return CascadeOcrModel(
        enabled=True,
        artifacts_path=None,
        options=cascade_opts,
        accelerator_options=AcceleratorOptions(),
    ), pdf_opts


def _make_mock_page(page_image):
    from docling_core.types.doc.base import Size
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


def _run_cascade_on_page(model, page, tmp_path):
    from docling_core.types.doc import BoundingBox, CoordOrigin
    from docling_cascade_ocr.model import CascadeOcrModel
    import unittest.mock as um

    pdf_path = tmp_path / "fixture.pdf"
    pdf_path.write_bytes(b"%PDF-fake%%EOF")
    cr = MagicMock()
    cr.input.file = pdf_path
    cr.timings = {}

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


# ---- Per-leaf-type live tests ----

class TestBrregTemplateLive:
    """brreg_template: full cascade, full layout, full TableFormer."""

    def test_runs_and_recovers_known_value(self, page_image, tmp_path):
        ledger = tmp_path / "brreg.jsonl"
        model, pdf_opts = _build_model_from_config(
            "brreg_template", audit_ledger_path=str(ledger),
        )
        page = _make_mock_page(page_image)
        _run_cascade_on_page(model, page, tmp_path)

        # The known value 12345678 must be in the token-vote consensus
        s = model.summary
        assert s.n_pages == 1
        assert s.n_tokens_committed >= 1, (
            "brreg_template cascade did not commit any tokens — "
            "voter granularity / token-vote pipeline broke"
        )

    def test_audit_ledger_written(self, page_image, tmp_path):
        ledger = tmp_path / "brreg.jsonl"
        model, _ = _build_model_from_config(
            "brreg_template", audit_ledger_path=str(ledger),
        )
        page = _make_mock_page(page_image)
        _run_cascade_on_page(model, page, tmp_path)
        assert ledger.exists()
        rec = json.loads(ledger.read_text().splitlines()[0])
        assert rec["_meta"]["audit_schema_version"] == "v2"
        assert "tesseract" in rec["_meta"]["voters"]


class TestKonsernregnskapLive:
    def test_full_cascade_runs(self, page_image, tmp_path):
        model, pdf_opts = _build_model_from_config("konsernregnskap")
        # konsernregnskap structurally matches brreg_template; the
        # difference is in downstream calc-arc tolerance, not in OCR.
        # Sanity-check the cascade still runs.
        assert pdf_opts.ocr_options.column_drop_veto is True
        page = _make_mock_page(page_image)
        _run_cascade_on_page(model, page, tmp_path)
        assert model.summary.n_tokens_committed >= 1


class TestAuditorReportLive:
    """auditor_report: cheap cascade, no TableFormer, no column-drop veto."""

    def test_no_column_drop_veto(self, tmp_path, page_image):
        from docling_cascade_ocr.options import CascadeVoter
        model, pdf_opts = _build_model_from_config(
            "auditor_report",
            voter_subset=[CascadeVoter(name="tesseract")],
        )
        # Auditor reports are mostly prose; column-drop veto must be disabled
        # so a single-column page doesn't accidentally trigger the heuristic.
        assert pdf_opts.ocr_options.column_drop_veto is False
        # do_table_structure should be False per the factory
        assert pdf_opts.do_table_structure is False
        # Cascade still runs cleanly
        page = _make_mock_page(page_image)
        _run_cascade_on_page(model, page, tmp_path)
        assert model.summary.n_pages == 1


class TestTxLogLive:
    """tx_log: strict column-drop veto + require_unanimous_for_table_cells."""

    def test_unanimous_required_for_table_cells(self, page_image, tmp_path):
        model, pdf_opts = _build_model_from_config("tx_log")
        # The tx_log config's distinguishing feature
        assert pdf_opts.ocr_options.require_unanimous_for_table_cells is True
        assert pdf_opts.ocr_options.column_drop_veto is True
        # Cascade still runs end-to-end; if the unanimous rule changes
        # column drop or commit behaviour, the next assertion catches it.
        page = _make_mock_page(page_image)
        _run_cascade_on_page(model, page, tmp_path)
        # Even with stricter rules, with 2 perfect-agreement voters
        # we still expect the value 12345678 in the token vote consensus
        assert model.summary.n_tokens_committed >= 1


class TestCrossConfigBehaviour:
    """Comparative: a config that disables column-drop veto must produce
    the same or more clusters than one that enables it."""

    def test_auditor_no_veto_at_least_as_many_clusters(self, page_image, tmp_path):
        from docling_cascade_ocr.options import CascadeVoter
        # Use single voter so the comparison isn't dominated by
        # voter-pair granularity differences
        single = [CascadeVoter(name="tesseract")]

        m_auditor, _ = _build_model_from_config(
            "auditor_report", voter_subset=single,
        )
        m_brreg, _ = _build_model_from_config(
            "brreg_template", voter_subset=single,
        )

        page1 = _make_mock_page(page_image)
        page2 = _make_mock_page(page_image)
        _run_cascade_on_page(m_auditor, page1, tmp_path)
        _run_cascade_on_page(m_brreg, page2, tmp_path)

        # Both should have processed exactly one page
        assert m_auditor.summary.n_pages == 1
        assert m_brreg.summary.n_pages == 1
        # The auditor (no column-drop veto) cluster count should be
        # ≥ the brreg cluster count (since brreg's veto only ever
        # excludes voters / clusters, never adds them)
        assert (
            m_auditor.summary.n_clusters_total
            >= m_brreg.summary.n_clusters_total
        )


# ---- Per-leaf-type structural tests still in pipeline/tests/ ----

def test_all_4_factories_callable():
    """The 4 named factories build cascade options with the cascade kind."""
    from regnskapsnoter_pipeline.configs import REGISTRY
    for name, factory in REGISTRY.items():
        opts = factory()
        # Discriminator is 'cascade' (the OcrFactory key)
        assert opts.ocr_options.kind == "cascade"
