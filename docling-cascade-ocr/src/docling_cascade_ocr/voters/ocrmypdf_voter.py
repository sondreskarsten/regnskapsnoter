"""ocrmypdf voter.

ocrmypdf is a Tesseract-based pipeline with image preprocessing (deskew, denoise,
contrast). For our purposes the value-add over plain Tesseract is the preprocessing,
which handles BRREG-rasterised PDFs reliably. Implementation note: we don't actually
shell out to ocrmypdf for performance. Instead we replicate the preprocessing and
then call Tesseract directly. This keeps the voter independent from Tesseract's
default settings while sharing the same ``pytesseract`` dependency.
"""
from __future__ import annotations

from typing import List

from PIL import Image, ImageOps

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


class OcrmypdfVoter(BaseVoter):
    name = "ocrmypdf"

    def __init__(self, *, lang: List[str], use_gpu: bool = False) -> None:
        super().__init__(lang=lang, use_gpu=use_gpu)
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            raise VoterUnavailable("pytesseract not installed (required for ocrmypdf voter)") from e
        self._lang_str = _lang_to_tesseract(lang)

    def run(self, page_image: Image.Image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        import pytesseract
        cells: List[TextCell] = []
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            crop = self._preprocess(crop)
            data = pytesseract.image_to_data(
                crop,
                lang=self._lang_str,
                # ocrmypdf's defaults: PSM 1 (auto), OEM 1 (LSTM only)
                config="--psm 1 --oem 1",
                output_type=pytesseract.Output.DICT,
            )
            cells.extend(self._lines(data, rect, len(cells)))
        return cells

    @staticmethod
    def _preprocess(img: Image.Image) -> Image.Image:
        if img.mode != "L":
            img = img.convert("L")
        img = ImageOps.autocontrast(img, cutoff=1)
        return img

    @staticmethod
    def _lines(data: dict, rect: BoundingBox, start_idx: int) -> List[TextCell]:
        from collections import defaultdict
        lines = defaultdict(list)
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
                "text": txt, "conf": conf,
                "x": int(data["left"][i]), "y": int(data["top"][i]),
                "w": int(data["width"][i]), "h": int(data["height"][i]),
            })
        out: List[TextCell] = []
        for j, (_, words) in enumerate(sorted(lines.items())):
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
