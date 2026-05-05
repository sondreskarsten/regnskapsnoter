"""EasyOCR voter."""
from __future__ import annotations

from typing import List

from PIL import Image
import numpy as np

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


class EasyOcrVoter(BaseVoter):
    name = "easyocr"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        super().__init__(lang=lang, use_gpu=use_gpu)
        try:
            import easyocr  # noqa
        except ImportError as e:
            raise VoterUnavailable("easyocr not installed") from e
        import easyocr
        # EasyOCR uses 'no' for Norwegian (Bokmål); 'nn' for Nynorsk; both Latin.
        ez_lang = ["no" if l in ("no", "nb") else l for l in lang if l in ("no", "nb", "nn", "en")]
        if not ez_lang:
            ez_lang = ["en"]
        self._reader = easyocr.Reader(ez_lang, gpu=use_gpu, verbose=False)

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            arr = np.array(crop)
            res = self._reader.readtext(arr)
            for line in res:
                box, txt, conf = line
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
