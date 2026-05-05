"""Per-leaf-type Docling ``PdfPipelineOptions`` factories.

Each Norwegian årsregnskap PDF falls into one of a small set of "leaf types"
that imply different OCR sensitivities, layout assumptions, and downstream
expectations. The 4 we ship by default:

- ``brreg_template`` — BRREG-rasterised PDFs (1728px width, 300 DPI). The
  default and most common case. Full cascade, full layout, full TableFormer.
- ``konsernregnskap`` — multi-entity consolidated regnskap. Stricter calc-arc
  validation tolerance; auditor signature pages are common at the end.
- ``auditor_report`` — standalone auditor reports (revisjonsberetning). Few
  numeric tables, mostly prose. Cheap cascade (3 voters), no TableFormer.
- ``tx_log`` — transaction log dumps. Massive tables, dense numerics. Cascade
  with strict column-drop veto.

Each factory returns a configured ``PdfPipelineOptions`` ready to feed into
``DocumentConverter``.
"""
from __future__ import annotations

from typing import Optional

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.pipeline_options import PdfPipelineOptions

from docling_cascade_ocr import CascadeOcrOptions, CascadeVoter


# -- Defaults --

_FULL_VOTERS = [
    CascadeVoter(name="ocrmypdf"),
    CascadeVoter(name="tesseract"),
    CascadeVoter(name="tesseract_tsv"),
    CascadeVoter(name="paddleocr"),
    CascadeVoter(name="doctr"),
    CascadeVoter(name="easyocr"),
]

_CHEAP_VOTERS = [
    CascadeVoter(name="ocrmypdf"),
    CascadeVoter(name="tesseract"),
    CascadeVoter(name="easyocr"),
]


def brreg_template(
    *,
    audit_ledger_path: Optional[str] = None,
    accelerator: Optional[AcceleratorOptions] = None,
) -> PdfPipelineOptions:
    """Standard BRREG-rasterised årsregnskap (the most common case)."""
    return PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        allow_external_plugins=True,
        generate_page_images=False,
        accelerator_options=accelerator or AcceleratorOptions(),
        ocr_options=CascadeOcrOptions(
            voters=list(_FULL_VOTERS),
            min_voters_for_commit=5,           # 5/6 enabled voters
            column_drop_veto=True,
            audit_ledger_path=audit_ledger_path,
            force_full_page_ocr=True,           # BRREG PDFs are pure raster
        ),
    )


def konsernregnskap(
    *,
    audit_ledger_path: Optional[str] = None,
    accelerator: Optional[AcceleratorOptions] = None,
) -> PdfPipelineOptions:
    """Consolidated regnskap. Same OCR profile as brreg_template, with
    stricter downstream validation tolerance applied at SHACL stage."""
    return PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        allow_external_plugins=True,
        accelerator_options=accelerator or AcceleratorOptions(),
        ocr_options=CascadeOcrOptions(
            voters=list(_FULL_VOTERS),
            min_voters_for_commit=5,
            column_drop_veto=True,
            audit_ledger_path=audit_ledger_path,
            force_full_page_ocr=True,
        ),
    )


def auditor_report(
    *,
    audit_ledger_path: Optional[str] = None,
    accelerator: Optional[AcceleratorOptions] = None,
) -> PdfPipelineOptions:
    """Standalone revisjonsberetning. Few tables, mostly prose."""
    return PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=False,                    # not numeric-heavy
        allow_external_plugins=True,
        accelerator_options=accelerator or AcceleratorOptions(),
        ocr_options=CascadeOcrOptions(
            voters=list(_CHEAP_VOTERS),
            min_voters_for_commit=2,                 # 2/3 cheap voters
            column_drop_veto=False,                  # rare to have columns
            audit_ledger_path=audit_ledger_path,
        ),
    )


def tx_log(
    *,
    audit_ledger_path: Optional[str] = None,
    accelerator: Optional[AcceleratorOptions] = None,
) -> PdfPipelineOptions:
    """Transaction log dumps. Dense numerics, many columns."""
    return PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        allow_external_plugins=True,
        accelerator_options=accelerator or AcceleratorOptions(),
        ocr_options=CascadeOcrOptions(
            voters=list(_FULL_VOTERS),
            min_voters_for_commit=5,
            column_drop_veto=True,                   # critical for tx logs
            require_unanimous_for_table_cells=True,  # tighter on numerics
            audit_ledger_path=audit_ledger_path,
        ),
    )


REGISTRY = {
    "brreg_template": brreg_template,
    "konsernregnskap": konsernregnskap,
    "auditor_report": auditor_report,
    "tx_log": tx_log,
}


def get_config(name: str, **kwargs) -> PdfPipelineOptions:
    """Look up a config by name, e.g. ``get_config("brreg_template")``."""
    factory = REGISTRY.get(name)
    if factory is None:
        raise ValueError(f"Unknown pipeline config: {name!r}. Known: {list(REGISTRY)}")
    return factory(**kwargs)
