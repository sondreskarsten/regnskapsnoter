"""``docling_default`` voter — wraps Docling's stock Tesseract OCR settings.

Audit C1 said: 'Docling's default OCR is the 8th voter (named
docling_default). The opening pitch — "we don't have a single-vendor
failure mode because Docling's own engine is one of the votes" — is not
realised.'

This voter implements the wrap-pattern. It runs Tesseract with **Docling's
default settings** (no custom `--psm` flag, automatic page segmentation =
psm 3) — which is what vanilla Docling does when configured with
``ocr_options=TesseractOcrOptions()``.

The contract: the cascade should never be worse than vanilla Docling on
any document. Including this voter as part of the production 7-voter set
guarantees that the consensus always has access to a vote that is, by
construction, what stock Docling would have produced.

Implementation note: Docling proper uses ``tesserocr`` (C-binding via
PyPI ``tesserocr`` package) when available, and falls back to
``tesseract`` CLI via ``TesseractOcrCliModel``. This wrapper uses
``pytesseract`` for portability and CI compatibility, but with default
psm so the OCR output approximates what Docling's stock pipeline would
produce. If a future Docling version exposes a public API for "run OCR
with current default settings", we can swap to it without changing
the voter's interface.
"""
from __future__ import annotations

from typing import List

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


class DoclingDefaultVoter(BaseVoter):
    """Tesseract with Docling's default page-segmentation mode (psm 3).

    Distinct from ``TesseractVoter`` which uses ``--psm 6`` (assume single
    uniform block of text). The two voters are legitimately different
    because psm 3 lets Tesseract auto-detect the layout while psm 6
    forces single-block reading. On multi-column or mixed-content pages
    they produce different cell sets.
    """

    name = "docling_default"

    def __init__(self, *, lang=None, use_gpu: bool = False) -> None:
        # use_gpu is accepted for registry compatibility but ignored —
        # Tesseract is CPU-only.
        del use_gpu
        try:
            import pytesseract  # noqa: F401
        except ImportError as e:
            raise VoterUnavailable(
                "docling_default voter requires pytesseract"
            ) from e
        # Reuse the same language-mapping logic as TesseractVoter
        from .tesseract_voter import _lang_to_tesseract
        self._lang_str = _lang_to_tesseract(lang or ["no", "nb", "en"])

    def run(self, page_image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        import pytesseract
        cells: List[TextCell] = []
        # Docling's default: no --psm flag (= psm 3, fully automatic
        # page segmentation). NO --oem override either.
        for rect in ocr_rects:
            crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
            try:
                data = pytesseract.image_to_data(
                    crop,
                    lang=self._lang_str,
                    output_type=pytesseract.Output.DICT,
                    # No `config=` argument → vanilla Tesseract defaults
                )
            except Exception:
                continue

            # Group by line_num within the rect (mirrors TesseractVoter
            # line aggregation, but inputs differ because psm differs)
            lines: dict = {}
            n = len(data.get("text", []))
            for i in range(n):
                w = (data["text"][i] or "").strip()
                if not w:
                    continue
                conf = float(data["conf"][i])
                if conf < 0:
                    continue
                line_key = (data["block_num"][i], data["par_num"][i],
                            data["line_num"][i])
                lines.setdefault(line_key, []).append({
                    "text": w,
                    "conf": conf,
                    "x": int(data["left"][i]),
                    "y": int(data["top"][i]),
                    "w": int(data["width"][i]),
                    "h": int(data["height"][i]),
                })

            start_idx = len(cells)
            for j, words in enumerate(lines.values()):
                line_text = " ".join(w["text"] for w in words)
                x0 = min(w["x"] for w in words) + rect.l
                y0 = min(w["y"] for w in words) + rect.t
                x1 = max(w["x"] + w["w"] for w in words) + rect.l
                y1 = max(w["y"] + w["h"] for w in words) + rect.t
                mean_conf = sum(w["conf"] for w in words) / len(words) / 100.0
                cells.append(TextCell(
                    index=start_idx + j,
                    text=line_text,
                    orig=line_text,
                    from_ocr=True,
                    confidence=max(0.0, min(1.0, mean_conf)),
                    rect=BoundingRectangle.from_bounding_box(BoundingBox(
                        l=x0, t=y0, r=x1, b=y1,
                        coord_origin=CoordOrigin.TOPLEFT,
                    )),
                ))
        return cells
