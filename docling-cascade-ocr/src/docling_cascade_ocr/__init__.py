"""docling-cascade-ocr — multi-DGP OCR voting plugin for Docling.

Activation:

    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling_cascade_ocr import CascadeOcrOptions

    pipe = PdfPipelineOptions(
        do_ocr=True,
        allow_external_plugins=True,
        ocr_options=CascadeOcrOptions(
            min_voters_for_commit=7,
            audit_ledger_path="/tmp/cascade_audit.jsonl",
        ),
    )
    converter = DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipe),
    })
"""
from .model import CascadeOcrModel
from .options import CascadeOcrOptions, CascadeVoter

__version__ = "0.1.0"

__all__ = ["CascadeOcrModel", "CascadeOcrOptions", "CascadeVoter", "ocr_engines"]


def ocr_engines():
    """Docling plugin entry point — returns the registered OCR model classes.

    Discovered automatically when:
      - this package is installed,
      - it has the ``[project.entry-points."docling"] cascade_ocr = "docling_cascade_ocr"``
        entry point declared in pyproject.toml,
      - the consumer passes ``allow_external_plugins=True`` to ``PdfPipelineOptions``.
    """
    return {"ocr_engines": [CascadeOcrModel]}
