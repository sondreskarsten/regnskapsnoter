"""PaddleOCR voter.

PaddleOCR's PP-OCRv4 ``en`` recognizer is the default. For Norwegian we use
``en`` because PaddleOCR doesn't ship a Bokmål/Nynorsk-specific model — Latin-script
Norwegian is read passably by the Latin recognizer. PaddleOCR is the strongest
voter on dense numeric tables in the v2 fixture.
"""
from __future__ import annotations

from typing import List

from PIL import Image
import numpy as np

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


class PaddleOcrVoter(BaseVoter):
    name = "paddleocr"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        super().__init__(lang=lang, use_gpu=use_gpu)
        try:
            from paddleocr import PaddleOCR  # noqa
        except ImportError as e:
            raise VoterUnavailable("paddleocr not installed") from e
        from paddleocr import PaddleOCR
        self._reader = PaddleOCR(use_angle_cls=True, lang="en", use_gpu=use_gpu, show_log=False)

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            arr = np.array(crop)
            res = self._reader.ocr(arr, cls=True)
            if not res or not res[0]:
                continue
            for j, line in enumerate(res[0]):
                box, (txt, conf) = line
                if not txt:
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                x0 = int(min(xs)) + rect.l
                y0 = int(min(ys)) + rect.t
                x1 = int(max(xs)) + rect.l
                y1 = int(max(ys)) + rect.t
                cells.append(TextCell(
                    index=len(cells),
                    text=txt,
                    orig=txt,
                    from_ocr=True,
                    confidence=float(conf),
                    rect=BoundingRectangle.from_bounding_box(BoundingBox(
                        l=x0, t=y0, r=x1, b=y1, coord_origin=CoordOrigin.TOPLEFT,
                    )),
                ))
        return cells
