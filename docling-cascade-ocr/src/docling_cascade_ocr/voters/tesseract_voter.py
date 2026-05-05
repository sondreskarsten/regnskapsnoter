"""Tesseract voters.

Two voters share the Tesseract LSTM backend but use different output paths:

- ``TesseractVoter`` runs the standard ``image_to_data`` flow and groups words
  into line-level cells. This is the closest analogue to ``ocrmypdf``'s default
  behaviour.
- ``TesseractTsvVoter`` runs ``image_to_data`` and emits one cell per Tesseract
  word, preserving per-word bounding boxes. This is what the cascade needs for
  the ``xalign_vote`` column-aware consensus rule.

Both voters use ``--psm 6`` (assume a single uniform block of text) which the
ocr-cascade-eval v2 fixture showed to be the best baseline for Norwegian
årsregnskap pages.
"""
from __future__ import annotations

from typing import List

from PIL import Image

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


def _lang_to_tesseract(lang: List[str]) -> str:
    mapping = {"no": "nor", "nb": "nor", "nn": "nor", "en": "eng"}
    seen = []
    for l in lang:
        t = mapping.get(l, l)
        if t not in seen:
            seen.append(t)
    return "+".join(seen) if seen else "nor"


class _TesseractBase(BaseVoter):
    name = "tesseract"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        super().__init__(lang=lang, use_gpu=use_gpu)
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            raise VoterUnavailable("pytesseract not installed") from e
        self._lang_str = _lang_to_tesseract(lang)


class TesseractVoter(_TesseractBase):
    """Line-level Tesseract output.

    Cells correspond to Tesseract's ``line_num`` grouping. Confidence is the mean of
    word-level confidences within the line, normalised to [0, 1]. Lines with negative
    or missing confidence are dropped.
    """

    name = "tesseract"

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        import pytesseract
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            data = pytesseract.image_to_data(
                crop,
                lang=self._lang_str,
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )
            cells.extend(self._group_lines(data, rect, len(cells)))
        return cells

    @staticmethod
    def _group_lines(data: dict, rect: BoundingBox, start_idx: int) -> List[TextCell]:
        from collections import defaultdict
        lines: dict = defaultdict(list)
        for i, txt in enumerate(data.get("text", [])):
            if not txt or not txt.strip():
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                continue
            if conf < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines[key].append({
                "text": txt,
                "conf": conf,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
            })

        out: List[TextCell] = []
        for j, (_, words) in enumerate(sorted(lines.items())):
            if not words:
                continue
            line_text = " ".join(w["text"] for w in words)
            x0 = min(w["x"] for w in words) + rect.l
            y0 = min(w["y"] for w in words) + rect.t
            x1 = max(w["x"] + w["w"] for w in words) + rect.l
            y1 = max(w["y"] + w["h"] for w in words) + rect.t
            mean_conf = sum(w["conf"] for w in words) / len(words) / 100.0
            out.append(TextCell(
                index=start_idx + j,
                text=line_text,
                orig=line_text,
                from_ocr=True,
                confidence=mean_conf,
                rect=BoundingRectangle.from_bounding_box(BoundingBox(
                    l=x0, t=y0, r=x1, b=y1, coord_origin=CoordOrigin.TOPLEFT,
                )),
            ))
        return out


class TesseractTsvVoter(_TesseractBase):
    """Word-level Tesseract output (one cell per word).

    Used by ``xalign_vote`` to detect column-drop on stacked balance tables.
    """

    name = "tesseract_tsv"

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        import pytesseract
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            data = pytesseract.image_to_data(
                crop,
                lang=self._lang_str,
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )
            for i, txt in enumerate(data.get("text", [])):
                if not txt or not txt.strip():
                    continue
                try:
                    conf = float(data["conf"][i])
                except (TypeError, ValueError):
                    continue
                if conf < 0:
                    continue
                x0 = int(data["left"][i]) + rect.l
                y0 = int(data["top"][i]) + rect.t
                x1 = x0 + int(data["width"][i])
                y1 = y0 + int(data["height"][i])
                cells.append(TextCell(
                    index=len(cells),
                    text=txt,
                    orig=txt,
                    from_ocr=True,
                    confidence=conf / 100.0,
                    rect=BoundingRectangle.from_bounding_box(BoundingBox(
                        l=x0, t=y0, r=x1, b=y1, coord_origin=CoordOrigin.TOPLEFT,
                    )),
                ))
        return cells
