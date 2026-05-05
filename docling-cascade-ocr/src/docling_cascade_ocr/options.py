"""Cascade OCR options.

Subclasses Docling's ``OcrOptions`` so it slots into the standard
``PdfPipelineOptions(ocr_options=…)`` flow. The ``kind`` literal is the discriminator
the OcrFactory uses to look up the correct model class.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from docling.datamodel.pipeline_options import OcrOptions


VoterName = Literal[
    "ocrmypdf",
    "tesseract",
    "tesseract_tsv",
    "paddleocr",
    "doctr",
    "easyocr",
    "pix2struct",
    "docling_default",
]


class CascadeVoter(BaseModel):
    """A single OCR voter in the cascade.

    A voter is one independent observation mechanism. Disable a voter by setting
    ``enabled=False`` rather than removing it from the list, so the run record still
    documents which voters were considered for this configuration.
    """

    name: VoterName
    enabled: bool = True
    weight: float = 1.0
    timeout_s: float = 60.0


def _default_voters() -> List[CascadeVoter]:
    return [
        CascadeVoter(name="ocrmypdf"),
        CascadeVoter(name="tesseract"),
        CascadeVoter(name="tesseract_tsv"),
        CascadeVoter(name="paddleocr"),
        CascadeVoter(name="doctr"),
        CascadeVoter(name="easyocr"),
        CascadeVoter(name="pix2struct", enabled=False),
    ]


class CascadeOcrOptions(OcrOptions):
    """Options for the cascade OCR engine.

    Defaults reflect the production verdict from ``ocr-cascade-eval`` (commit
    ``ffe4d35``):

    - 7 voters enabled
    - vote when at least 7 voters agree on a cell
    - column-drop veto active (any voter that drops a column is excluded from the page)
    - audit ledger off by default; set ``audit_ledger_path`` to enable
    """

    kind: Literal["cascade"] = "cascade"  # type: ignore[assignment]

    voters: List[CascadeVoter] = Field(default_factory=_default_voters)

    # Voting policy
    min_voters_for_commit: int = 7
    require_unanimous_for_table_cells: bool = False
    use_xalign_vote: bool = True
    column_drop_veto: bool = True

    # Audit
    audit_ledger_path: Optional[str] = None

    # Engine-shared OCR knobs
    lang: List[str] = Field(default_factory=lambda: ["no", "nb", "nn", "en"])
    bitmap_area_threshold: float = 0.05
    force_full_page_ocr: bool = False

    model_config = {"extra": "forbid"}
