"""Tests for the docling-eval prediction provider (audit C4).

Verifies:
- The provider subclasses ``BasePredictionProvider`` correctly
- ``info()`` returns the expected keys with sensible values
- ``prediction_format`` is ``DOCLING_DOCUMENT``
- ``predict()`` on a non-existent PDF returns a record with
  ``status=FAILURE: ...`` rather than crashing the eval loop
- The stub raises ImportError when ``docling-eval`` is not installed
"""
from __future__ import annotations

import pytest


def _has_docling_eval() -> bool:
    try:
        import docling_eval  # noqa
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _has_docling_eval(),
    reason="docling-eval not installed",
)
class TestCascadePredictionProvider:
    def test_provider_subclasses_base(self):
        from docling_eval.prediction_providers.base_prediction_provider import (
            BasePredictionProvider,
        )
        from regnskapsnoter_eval.cascade_provider import (
            CascadePredictionProvider,
        )
        provider = CascadePredictionProvider()
        assert isinstance(provider, BasePredictionProvider)

    def test_prediction_format_is_doclingdocument(self):
        from docling_eval.datamodels.types import PredictionFormats
        from regnskapsnoter_eval.cascade_provider import (
            CascadePredictionProvider,
        )
        assert (
            CascadePredictionProvider.prediction_format
            == PredictionFormats.DOCLING_DOCUMENT
        )

    def test_info_keys(self):
        from regnskapsnoter_eval.cascade_provider import (
            CascadePredictionProvider,
        )
        provider = CascadePredictionProvider()
        info = provider.info()
        assert info["predictor_name"] == "regnskapsnoter-cascade"
        assert "predictor_version" in info
        assert "n_voters_configured" in info
        assert "n_voters_enabled" in info

    def test_info_defaults_match_cascade_options_defaults(self):
        from docling_cascade_ocr.options import CascadeOcrOptions
        from regnskapsnoter_eval.cascade_provider import (
            CascadePredictionProvider,
        )
        provider = CascadePredictionProvider()
        info = provider.info()
        # The reported voter count must equal the actual default voter count
        opts = CascadeOcrOptions()
        assert info["n_voters_configured"] == str(len(opts.voters))
        # Enabled count: defaults disable pix2struct + document_ai → opts - 2
        n_enabled = sum(1 for v in opts.voters if v.enabled)
        assert info["n_voters_enabled"] == str(n_enabled)

    def test_info_with_custom_options(self):
        from docling_cascade_ocr.options import CascadeOcrOptions, CascadeVoter
        from regnskapsnoter_eval.cascade_provider import (
            CascadePredictionProvider,
        )
        opts = CascadeOcrOptions(
            voters=[CascadeVoter(name="tesseract"),
                     CascadeVoter(name="docling_default")],
        )
        provider = CascadePredictionProvider(cascade_options=opts)
        info = provider.info()
        assert info["n_voters_configured"] == "2"
        assert info["n_voters_enabled"] == "2"

    def test_predict_handles_missing_pdf(self, tmp_path):
        """A non-existent PDF must not crash the eval loop —
        provider returns status=FAILURE and a None predicted_doc."""
        from docling_core.types.doc import DoclingDocument
        from docling_eval.datamodels.dataset_record import DatasetRecord
        from regnskapsnoter_eval.cascade_provider import (
            CascadePredictionProvider,
        )
        provider = CascadePredictionProvider()

        bogus_path = tmp_path / "does_not_exist.pdf"
        # Minimal empty DoclingDocument as the ground-truth placeholder
        gt = DoclingDocument(name="missing")
        record = DatasetRecord(
            doc_id="missing",
            doc_path=bogus_path,
            doc_hash="0" * 64,
            ground_truth_doc=gt,
            mime_type="application/pdf",
        )

        result = provider.predict(record)
        from docling.datamodel.base_models import ConversionStatus
        assert result.predicted_doc is None
        assert result.status == ConversionStatus.FAILURE
        # The error message is preserved in predictor_info for debugging
        assert "error" in result.predictor_info


def test_stub_raises_when_docling_eval_unavailable():
    """If docling-eval isn't importable, instantiating raises ImportError.

    This test would only fail if docling-eval is somehow imported but
    fails at runtime — in normal CI it's a no-op (skipped or trivially
    passing). It's here to document the contract.
    """
    if _has_docling_eval():
        pytest.skip("docling-eval IS installed; stub path not exercised")
    from regnskapsnoter_eval.cascade_provider import (
        CascadePredictionProvider,
    )
    with pytest.raises(ImportError):
        CascadePredictionProvider()
