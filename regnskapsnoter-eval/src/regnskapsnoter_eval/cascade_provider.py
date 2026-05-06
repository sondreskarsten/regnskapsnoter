"""docling-eval prediction provider for the cascade (audit C4).

Wraps :class:`CascadeOcrModel` as a :class:`BasePredictionProvider`
subclass so it plugs straight into ``docling-eval``'s formal evaluation
pipeline. Pair this with any ``OcrEvaluator`` /
``MarkdownTextEvaluator`` / ``LayoutEvaluator`` to get the same metrics
docling-eval applies to its own benchmark datasets.

Usage:

    from regnskapsnoter_eval.cascade_provider import CascadePredictionProvider
    from docling_eval.evaluators.ocr_evaluator import OcrEvaluator

    provider = CascadePredictionProvider(
        cascade_options=CascadeOcrOptions(...),
    )
    # docling-eval drives this:
    for record in dataset:
        prediction = provider.predict(record)
        evaluator.evaluate(record, prediction)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _has_docling_eval() -> bool:
    try:
        import docling_eval  # noqa
        return True
    except ImportError:
        return False


if _has_docling_eval():
    from docling_eval.datamodels.dataset_record import (
        DatasetRecord,
        DatasetRecordWithPrediction,
    )
    from docling_eval.datamodels.types import PredictionFormats
    from docling_eval.prediction_providers.base_prediction_provider import (
        BasePredictionProvider,
    )

    class CascadePredictionProvider(BasePredictionProvider):
        """A docling-eval prediction provider backed by the cascade.

        The cascade runs end-to-end for each ``DatasetRecord``:
        DocumentConverter loads the source PDF, the cascade replaces
        the OCR step with multi-voter consensus, and the resulting
        DoclingDocument is returned as the prediction.

        Args:
            cascade_options: optional ``CascadeOcrOptions``. If None,
                the defaults are used (8 voters incl. docling_default).
            do_visualization: forwarded to BasePredictionProvider.
        """

        prediction_format = PredictionFormats.DOCLING_DOCUMENT

        def __init__(
            self,
            cascade_options=None,
            *,
            do_visualization: bool = False,
            **kwargs,
        ):
            super().__init__(
                do_visualization=do_visualization, **kwargs,
            )
            self._cascade_options = cascade_options

        def info(self) -> Dict[str, str]:
            from docling_cascade_ocr import __version__ as cv
            from docling_cascade_ocr.options import CascadeOcrOptions
            opts = self._cascade_options or CascadeOcrOptions()
            return {
                "predictor_name": "regnskapsnoter-cascade",
                "predictor_version": str(cv),
                "n_voters_configured": str(len(opts.voters)),
                "n_voters_enabled": str(
                    sum(1 for v in opts.voters if v.enabled)
                ),
            }

        def predict(self, record: DatasetRecord) -> DatasetRecordWithPrediction:
            """Run the cascade against the record's source PDF."""
            import os
            os.environ.setdefault("DOCLING_ALLOW_EXTERNAL_PLUGINS", "true")

            from docling.datamodel.base_models import (
                ConversionStatus, InputFormat,
            )
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import (
                DocumentConverter, PdfFormatOption,
            )
            from docling_cascade_ocr.options import CascadeOcrOptions

            opts = self._cascade_options or CascadeOcrOptions()
            pipeline_options = PdfPipelineOptions(
                ocr_options=opts,
                do_table_structure=True,
            )
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options,
                    ),
                },
            )
            predictor_info = self.info()
            try:
                result = converter.convert(record.doc_path)
                predicted_doc = result.document
                status = ConversionStatus.SUCCESS
            except Exception as e:
                predicted_doc = None
                status = ConversionStatus.FAILURE
                # Surface the cause via predictor_info — the schema
                # only has a status enum, not a free-form error field.
                predictor_info = {
                    **predictor_info,
                    "error": f"{type(e).__name__}: {e}",
                }

            return DatasetRecordWithPrediction(
                **record.model_dump(),
                predicted_doc=predicted_doc,
                predictor_info=predictor_info,
                status=status,
            )
else:
    class CascadePredictionProvider:  # type: ignore[no-redef]
        """Stub raised when docling-eval is not installed."""

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "CascadePredictionProvider requires docling-eval. "
                "Install with: pip install docling-eval"
            )
