"""DocTR voter (text mode).

Note: DocTR's bbox output (``doctr_bbox``) was DROPPED from production in the
v2 cascade because of row-clustering brittleness on stacked balance tables.
We keep the text-mode version here since it has independent failure modes from
Tesseract on hand-stamped page numbers.
"""
from __future__ import annotations

from typing import List

from PIL import Image
import numpy as np

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


class DoctrVoter(BaseVoter):
    name = "doctr"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        super().__init__(lang=lang, use_gpu=use_gpu)
        try:
            from doctr.models import ocr_predictor  # noqa
        except ImportError as e:
            raise VoterUnavailable("python-doctr not installed") from e
        from doctr.models import ocr_predictor
        self._predictor = ocr_predictor(pretrained=True)

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            arr = np.array(crop.convert("RGB"))
            doc = self._predictor([arr])
            page = doc.pages[0]
            W, H = crop.width, crop.height
            for block in page.blocks:
                for line in block.lines:
                    txt = " ".join(w.value for w in line.words)
                    if not txt.strip():
                        continue
                    confs = [w.confidence for w in line.words] or [1.0]
                    (x0n, y0n), (x1n, y1n) = line.geometry
                    x0 = int(x0n * W) + rect.l
                    y0 = int(y0n * H) + rect.t
                    x1 = int(x1n * W) + rect.l
                    y1 = int(y1n * H) + rect.t
                    cells.append(TextCell(
                        index=len(cells),
                        text=txt,
                        orig=txt,
                        from_ocr=True,
                        confidence=float(sum(confs) / len(confs)),
                        rect=BoundingRectangle.from_bounding_box(BoundingBox(
                            l=x0, t=y0, r=x1, b=y1, coord_origin=CoordOrigin.TOPLEFT,
                        )),
                    ))
        return cells
