"""Test that the cascade plugin registers correctly with Docling's plugin system."""
from __future__ import annotations

import pytest


def test_options_kind_is_cascade():
    from docling_cascade_ocr import CascadeOcrOptions
    opts = CascadeOcrOptions()
    assert opts.kind == "cascade"


def test_default_voters():
    from docling_cascade_ocr import CascadeOcrOptions
    opts = CascadeOcrOptions()
    enabled = [v.name for v in opts.voters if v.enabled]
    # 7 production voters; pix2struct disabled by default (lazy tiebreaker)
    assert "ocrmypdf" in enabled
    assert "tesseract" in enabled
    assert "tesseract_tsv" in enabled
    assert "paddleocr" in enabled
    assert "doctr" in enabled
    assert "easyocr" in enabled
    assert "pix2struct" not in enabled


def test_entry_point_function_returns_correct_shape():
    from docling_cascade_ocr import ocr_engines, CascadeOcrModel
    config = ocr_engines()
    assert "ocr_engines" in config
    assert CascadeOcrModel in config["ocr_engines"]


def test_get_options_type_returns_cascade_options():
    from docling_cascade_ocr import CascadeOcrModel, CascadeOcrOptions
    assert CascadeOcrModel.get_options_type() is CascadeOcrOptions


def test_plugin_discoverable_via_pluggy():
    """Simulate Docling's pluggy-based discovery.

    This requires the package to be installed in editable mode and have its entry
    point declared.
    """
    pytest.importorskip("pluggy")
    from importlib.metadata import entry_points
    eps = entry_points(group="docling")
    names = [e.name for e in eps]
    assert "cascade_ocr" in names, (
        f"cascade_ocr entry point not found. Installed entry points: {names}. "
        "Reinstall the package with `pip install -e .` to pick up entry points."
    )
