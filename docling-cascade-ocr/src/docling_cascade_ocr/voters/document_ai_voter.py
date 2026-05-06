"""``document_ai`` voter — Gemini Vision via Vertex AI REST.

Audit C2 closed: this voter calls ``gemini-2.5-flash`` with a rendered
page image and asks for the visible text. It costs API quota per call,
so the voter is designed to fire LAZILY (only on disagreement regions)
plus on a small random sample of unanimous pages for audit signal.

Combined with the lazy mechanism (audit C3) and the sample_rate field on
CascadeVoter (added for this voter), the typical production
configuration is:

    CascadeVoter(name="document_ai", enabled=True, lazy=True,
                  sample_rate=0.05)

— meaning it fires on 100% of disagreement regions + 5% random sample of
unanimous pages.

Project conventions baked in:
- Vertex AI ``us-central1`` endpoint (per memory note about EUROPE-NORTH2
  inline-base64 PDFs — for images we use US central directly)
- ``thinkingBudget=0`` for extraction (16× cost difference)
- ``temperature=0.0``
- Uses application-default credentials via ``google.auth.default``
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
from typing import List, Optional

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from .base import BaseVoter, VoterUnavailable


_log = logging.getLogger(__name__)


class DocumentAiVoter(BaseVoter):
    """Gemini Vision (Vertex AI) text extraction voter.

    Sends a page-region image to Gemini and asks for the visible text.
    Each newline becomes one TextCell; bbox is set to the rect we sent
    in (Gemini doesn't give us per-line bboxes back, so we use the
    parent rect as a fallback).
    """

    name = "document_ai"

    def __init__(
        self,
        *,
        lang=None,
        use_gpu: bool = False,
        model: str = "gemini-2.5-flash",
        location: str = "us-central1",
        project_id: Optional[str] = None,
    ):
        del use_gpu  # accepted for registry compatibility
        # Lazy-import google-auth so the voter can be referenced even
        # when its deps aren't installed (build_voters will skip it).
        try:
            import google.auth  # noqa: F401
            import requests  # noqa: F401
        except ImportError as e:
            raise VoterUnavailable(
                "document_ai voter requires google-auth + requests. "
                "Install with: pip install google-auth requests"
            ) from e

        self.lang = lang or ["no", "nb", "en"]
        self.model = model
        self.location = location
        self.project_id = (
            project_id
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or "sondreskarsten-d7d14"  # project default
        )

    # ---- Helpers (broken out for testability) ----

    def _build_request_body(self, image_b64: str) -> dict:
        """Build the JSON body sent to Vertex AI.

        Pure function for unit-testability (no network).
        """
        prompt = (
            "Extract all visible text from this image. Output one line per "
            "visual line in the image. Do NOT add explanations or formatting. "
            "Preserve numbers exactly as visible (including spaces in '12 345')."
        )
        return {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {
                        "mime_type": "image/png",
                        "data": image_b64,
                    }},
                ],
            }],
            "generationConfig": {
                "temperature": 0.0,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

    def _parse_response_text(self, text: str) -> List[str]:
        """Parse Gemini's response into one cell-text per line.

        Filters empty lines; preserves leading/trailing whitespace within a line.
        """
        lines = []
        for line in text.split("\n"):
            line = line.strip()
            if line:
                lines.append(line)
        return lines

    def _crop_to_b64(self, page_image, rect) -> str:
        """Crop the page image to the rect and base64-encode as PNG."""
        crop = page_image.crop((rect.l, rect.t, rect.r, rect.b))
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    # ---- Network call (skipped in unit tests via _call_vertex override) ----

    def _call_vertex(self, body: dict) -> dict:
        import google.auth
        import google.auth.transport.requests
        import requests

        creds, _ = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())

        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.location}/"
            f"publishers/google/models/{self.model}:generateContent"
        )
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def _extract_text_from_response(self, response_json: dict) -> str:
        """Pull the response text out of the Vertex AI envelope."""
        candidates = response_json.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    # ---- BaseVoter interface ----

    def run(self, page_image, ocr_rects: List[BoundingBox]) -> List[TextCell]:
        cells: List[TextCell] = []
        for rect in ocr_rects:
            try:
                image_b64 = self._crop_to_b64(page_image, rect)
                body = self._build_request_body(image_b64)
                response = self._call_vertex(body)
                text = self._extract_text_from_response(response)
            except Exception as e:
                _log.warning("document_ai voter failed on rect: %s", e)
                continue

            lines = self._parse_response_text(text)
            for i, line in enumerate(lines):
                cells.append(TextCell(
                    index=len(cells),
                    text=line,
                    orig=line,
                    from_ocr=True,
                    confidence=0.95,  # Gemini is confident; downstream
                                      # vote share is the truer signal
                    rect=BoundingRectangle.from_bounding_box(BoundingBox(
                        l=rect.l, t=rect.t, r=rect.r, b=rect.b,
                        coord_origin=CoordOrigin.TOPLEFT,
                    )),
                ))
        return cells
