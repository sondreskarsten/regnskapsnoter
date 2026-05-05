"""Voter base class and registry.

A voter is one OCR engine in the cascade. Each voter exposes a single ``run`` method
that takes the page raster (PIL.Image) plus the OCR rectangles (where to look) and
returns a list of ``TextCell``s. The cascade harness doesn't care how the voter
produces those cells — only that they are independent observations of the same
underlying pixels.

Voters are loaded lazily so that ``docling-cascade-ocr`` can be installed without all
engine extras present. A missing engine surfaces as ``VoterUnavailable`` at construction
time, not at import time.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

from PIL import Image

from docling_core.types.doc import BoundingBox
from docling_core.types.doc.page import TextCell

_log = logging.getLogger(__name__)


class VoterUnavailable(RuntimeError):
    """Raised when a voter's engine package is not installed."""


class BaseVoter(ABC):
    """Abstract OCR voter."""

    name: str = "base"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        self.lang = lang
        self.use_gpu = use_gpu

    @abstractmethod
    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        """Run OCR on the given page image, restricted to ``ocr_rects``.

        Coordinates in returned ``TextCell.rect`` MUST be in the same coordinate
        system as ``ocr_rects`` (Docling page coordinates, ``CoordOrigin.TOPLEFT``).
        """
        raise NotImplementedError


def build_voters(specs, *, lang, use_gpu) -> List[BaseVoter]:
    """Build the voter instances from the options' voter specs.

    Skips voters whose engine package is unavailable rather than failing the whole
    cascade — this lets callers run a 5-voter subset on a machine without paddle.
    """
    from .tesseract_voter import TesseractTsvVoter, TesseractVoter
    from .ocrmypdf_voter import OcrmypdfVoter
    from .paddleocr_voter import PaddleOcrVoter
    from .doctr_voter import DoctrVoter
    from .easyocr_voter import EasyOcrVoter
    from .pix2struct_voter import Pix2StructVoter

    registry = {
        "ocrmypdf": OcrmypdfVoter,
        "tesseract": TesseractVoter,
        "tesseract_tsv": TesseractTsvVoter,
        "paddleocr": PaddleOcrVoter,
        "doctr": DoctrVoter,
        "easyocr": EasyOcrVoter,
        "pix2struct": Pix2StructVoter,
    }
    out: List[BaseVoter] = []
    for spec in specs:
        if not spec.enabled:
            continue
        cls = registry.get(spec.name)
        if cls is None:
            _log.warning("Unknown voter: %s", spec.name)
            continue
        try:
            out.append(cls(lang=lang, use_gpu=use_gpu))
        except VoterUnavailable as e:
            _log.warning("Skipping voter %s: %s", spec.name, e)
    return out
