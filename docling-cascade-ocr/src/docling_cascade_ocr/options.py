"""Cascade OCR options.

Subclasses Docling's ``OcrOptions`` so it slots into the standard
``PdfPipelineOptions(ocr_options=…)`` flow. The ``kind`` ClassVar is the
discriminator the OcrFactory uses to look up the correct model class.
"""
from __future__ import annotations

from typing import ClassVar, List, Literal, Optional

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
    "document_ai",
]


class CascadeVoter(BaseModel):
    """A single OCR voter in the cascade.

    A voter is one independent observation mechanism. Disable a voter by setting
    ``enabled=False`` rather than removing it from the list, so the run record still
    documents which voters were considered for this configuration.

    ``lazy=True`` voters are tiebreakers (audit C3): they run only on
    regions where the eager voters disagreed. pix2struct is the canonical
    lazy voter — visual extraction is too expensive to run on every page,
    but cheap enough to call when the OCR cascade can't reach consensus.

    ``sample_rate`` (audit C2): a number in [0.0, 1.0]. If > 0, the voter
    fires on a random ``sample_rate`` fraction of pages even when there is
    no disagreement. Combined with ``lazy=True``, this gives the
    Document-AI / Gemini-Vision pattern: 100% on disagreement + N%
    sampled audit on otherwise-unanimous pages.
    """

    name: VoterName
    enabled: bool = True
    weight: float = 1.0
    timeout_s: float = 60.0
    lazy: bool = False
    sample_rate: float = 0.0


def _default_voters() -> List[CascadeVoter]:
    return [
        # Production 7 from ocr-cascade-eval v2
        CascadeVoter(name="ocrmypdf"),
        CascadeVoter(name="tesseract"),
        CascadeVoter(name="tesseract_tsv"),
        CascadeVoter(name="paddleocr"),
        CascadeVoter(name="doctr"),
        CascadeVoter(name="easyocr"),
        # pix2struct as a LAZY tiebreaker (audit C3) — runs only on
        # regions where the eager voters disagreed
        CascadeVoter(name="pix2struct", enabled=False, lazy=True),
        # Wrap-pattern (audit C1): always include Docling's stock default
        # so the cascade is never worse than vanilla Docling.
        CascadeVoter(name="docling_default"),
        # Document AI / Gemini Vision (audit C2): off by default since it
        # requires API credentials. When enabled, it runs lazily on
        # disagreement regions PLUS a 5% random sample of unanimous pages
        # for ongoing audit signal.
        CascadeVoter(name="document_ai", enabled=False, lazy=True,
                      sample_rate=0.05),
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

    kind: ClassVar[Literal["cascade"]] = "cascade"

    voters: List[CascadeVoter] = Field(default_factory=_default_voters)

    # Voting policy
    min_voters_for_commit: int = 7
    require_unanimous_for_table_cells: bool = False
    use_xalign_vote: bool = True
    column_drop_veto: bool = True

    # Vote mode — bbox-cluster vote, token-level vote, or both.
    # The token-level vote is required when voters disagree on cell
    # granularity (e.g. a line-mode TesseractVoter alongside a word-mode
    # TesseractTsvVoter): bbox clustering would mis-pair line and word
    # bboxes, but token voting on the union of numeric tokens is robust.
    # See ``token_vote.py`` for the algorithm and the v2-fixture audit
    # for the empirical motivation.
    vote_mode: Literal["bbox", "token", "both"] = "both"

    # Audit
    audit_ledger_path: Optional[str] = None

    # Engine-shared OCR knobs
    lang: List[str] = Field(default_factory=lambda: ["no", "nb", "nn", "en"])
    bitmap_area_threshold: float = 0.05
    force_full_page_ocr: bool = False

    model_config = {"extra": "forbid"}
