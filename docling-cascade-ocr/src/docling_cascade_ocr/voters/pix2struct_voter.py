"""pix2struct visual voter.

This voter is invoked LAZILY: only on cells where the text-mode voters disagree.
It is the most expensive voter (full visual transformer, ~1s/cell on CPU), so the
cascade harness skips it for unanimous cells.

The voter exposes the same ``run`` signature for uniformity, but the cascade will
typically call it via the harness's lazy-tiebreaker hook rather than as a
first-class voter.
"""
from __future__ import annotations

from typing import List

from PIL import Image

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


class Pix2StructVoter(BaseVoter):
    name = "pix2struct"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        super().__init__(lang=lang, use_gpu=use_gpu)
        try:
            from transformers import Pix2StructForConditionalGeneration, Pix2StructProcessor  # noqa
        except ImportError as e:
            raise VoterUnavailable("transformers not installed") from e
        try:
            import torch  # noqa
        except ImportError as e:
            raise VoterUnavailable("torch not installed") from e

        from transformers import Pix2StructForConditionalGeneration, Pix2StructProcessor
        import torch
        self._model_id = "google/pix2struct-base"
        self._device = "cuda" if (use_gpu and torch.cuda.is_available()) else "cpu"
        self._processor = Pix2StructProcessor.from_pretrained(self._model_id)
        self._model = Pix2StructForConditionalGeneration.from_pretrained(self._model_id).to(self._device)

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        import torch
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            inputs = self._processor(images=crop, return_tensors="pt").to(self._device)
            with torch.no_grad():
                outs = self._model.generate(**inputs, max_new_tokens=128)
            txt = self._processor.batch_decode(outs, skip_special_tokens=True)[0]
            if not txt.strip():
                continue
            cells.append(TextCell(
                index=len(cells),
                text=txt,
                orig=txt,
                from_ocr=True,
                confidence=0.9,  # pix2struct doesn't expose token-level conf
                rect=BoundingRectangle.from_bounding_box(BoundingBox(
                    l=rect.l, t=rect.t, r=rect.r, b=rect.b, coord_origin=CoordOrigin.TOPLEFT,
                )),
            ))
        return cells
