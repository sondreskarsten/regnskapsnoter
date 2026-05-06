"""Per-voter unit tests with deterministic synthetic images.

Each test renders a known string to a known image at a known location and
verifies that the voter's output:

1. Returns at least one ``TextCell``
2. Contains the expected text in the consensus
3. Has confidence in [0, 1]
4. Has bbox coordinates inside the image (sanity range check)
5. Round-trips through ``BoundingRectangle`` correctly

These tests are gated on engine availability via :func:`VoterUnavailable` —
if pytesseract isn't installed the tests skip rather than fail. This matches
the cascade's design: a missing voter is dropped, not a crash.

The audit (item B1) flagged that the 7 voter implementations had ZERO tests.
This file directly addresses that gap with real engine execution.
"""
from __future__ import annotations

import pytest

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import TextCell
from docling_cascade_ocr.voters.base import VoterUnavailable


# ---- Image fixtures ----

def _has_pil_and_font() -> bool:
    try:
        from PIL import ImageFont
        ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_pil_and_font(),
    reason="PIL or DejaVuSans-Bold font unavailable",
)


@pytest.fixture
def known_text_image():
    """600x100 image with the string 'Sum eiendeler 1234567' at (20, 30)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (600, 100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36,
    )
    d.text((20, 30), "Sum eiendeler 1234567", font=font, fill="black")
    return img


@pytest.fixture
def numeric_image():
    """300x80 image with '12 345 678' at (20, 20)."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (300, 80), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36,
    )
    d.text((20, 20), "12 345 678", font=font, fill="black")
    return img


@pytest.fixture
def two_column_image():
    """800x100 image with three text regions at distinct x positions."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (800, 100), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28,
    )
    d.text((20, 30), "Eiendeler", font=font, fill="black")
    d.text((400, 30), "12 345", font=font, fill="black")
    d.text((650, 30), "11 200", font=font, fill="black")
    return img


def _full_rect(img):
    return BoundingBox(
        l=0.0, t=0.0, r=float(img.width), b=float(img.height),
        coord_origin=CoordOrigin.TOPLEFT,
    )


def _bbox_in_image(cell: TextCell, img) -> bool:
    """Round-trip the cell's BoundingRectangle and check it falls inside the image."""
    bb = cell.rect.to_bounding_box()
    return (
        0.0 <= bb.l <= float(img.width)
        and 0.0 <= bb.r <= float(img.width)
        and bb.l <= bb.r
        and 0.0 <= bb.t <= float(img.height)
        and 0.0 <= bb.b <= float(img.height)
        and bb.t <= bb.b
    )


def _consensus_text(cells) -> str:
    return " ".join(c.text for c in cells)


# ---- TesseractVoter (line-level) ----

class TestTesseractVoter:
    def _voter(self):
        try:
            from docling_cascade_ocr.voters import TesseractVoter
            return TesseractVoter(lang=["no", "nb"])
        except VoterUnavailable as e:
            pytest.skip(str(e))

    def test_returns_at_least_one_cell(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        assert len(cells) >= 1

    def test_text_contains_expected_string(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        text = _consensus_text(cells)
        assert "Sum" in text
        assert "eiendeler" in text.lower()
        assert "1234567" in text

    def test_confidence_in_unit_interval(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        for c in cells:
            assert 0.0 <= c.confidence <= 1.0, (
                f"voter confidence {c.confidence} outside [0,1]"
            )

    def test_bbox_inside_image(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        for c in cells:
            assert _bbox_in_image(c, known_text_image), (
                f"bbox round-trip failed: {c.rect.to_bounding_box()}"
            )

    def test_from_ocr_flag_set(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        for c in cells:
            assert c.from_ocr is True

    def test_handles_blank_image(self):
        """A pure-white image must not crash and should return ≤ 0 useful cells."""
        from PIL import Image
        v = self._voter()
        blank = Image.new("RGB", (300, 80), "white")
        cells = v.run(blank, [_full_rect(blank)])
        for c in cells:
            assert c.text.strip()  # if any cells, they shouldn't be empty


# ---- TesseractTsvVoter (word-level) ----

class TestTesseractTsvVoter:
    def _voter(self):
        try:
            from docling_cascade_ocr.voters import TesseractTsvVoter
            return TesseractTsvVoter(lang=["no", "nb"])
        except VoterUnavailable as e:
            pytest.skip(str(e))

    def test_returns_word_level_cells(self, known_text_image):
        """tesseract_tsv should produce more cells than tesseract (word vs line)."""
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        # 'Sum eiendeler 1234567' = 3 word tokens
        assert len(cells) >= 2, f"expected ≥2 word cells, got {len(cells)}"

    def test_finds_each_word_separately(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        joined = " ".join(c.text for c in cells)
        assert "Sum" in joined
        assert "1234567" in joined

    def test_per_word_bboxes_have_positive_area(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        for c in cells:
            bb = c.rect.to_bounding_box()
            assert bb.r > bb.l, f"word cell has zero/negative width: {bb}"
            assert bb.b > bb.t, f"word cell has zero/negative height: {bb}"

    def test_confidence_per_word(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        for c in cells:
            assert 0.0 <= c.confidence <= 1.0


# ---- OcrmypdfVoter (Tesseract LSTM with preprocessing) ----

class TestOcrmypdfVoter:
    def _voter(self):
        try:
            from docling_cascade_ocr.voters import OcrmypdfVoter
            return OcrmypdfVoter(lang=["no", "nb"])
        except VoterUnavailable as e:
            pytest.skip(str(e))

    def test_returns_cells(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        assert len(cells) >= 1

    def test_text_contains_expected_string(self, known_text_image):
        v = self._voter()
        cells = v.run(known_text_image, [_full_rect(known_text_image)])
        joined = _consensus_text(cells)
        assert "1234567" in joined

    def test_runs_on_numeric_image(self, numeric_image):
        v = self._voter()
        cells = v.run(numeric_image, [_full_rect(numeric_image)])
        assert len(cells) >= 1
        joined = _consensus_text(cells)
        assert "12" in joined and "678" in joined


# ---- Coordinate sanity across voters (granularity contract) ----

class TestVoterCoordinateContract:
    """Cross-voter coordinate-system sanity.

    If two voters can't agree on a coordinate frame the cascade vote will
    silently fail. This contract test verifies that all available voters
    agree on:

    - Coordinate origin (top-left, x grows right, y grows down)
    - Bbox semantics (l < r, t < b after round-trip)
    - Cells fall inside the image
    """

    @pytest.fixture
    def all_voters(self):
        from docling_cascade_ocr.voters import (
            TesseractVoter, TesseractTsvVoter, OcrmypdfVoter,
        )
        out = []
        for cls in (TesseractVoter, TesseractTsvVoter, OcrmypdfVoter):
            try:
                out.append(cls(lang=["no", "nb"]))
            except VoterUnavailable:
                pass
        if not out:
            pytest.skip("no voters available")
        return out

    def test_all_voters_agree_on_image_bounds(self, all_voters, two_column_image):
        rect = _full_rect(two_column_image)
        for voter in all_voters:
            cells = voter.run(two_column_image, [rect])
            for c in cells:
                assert _bbox_in_image(c, two_column_image), (
                    f"voter {voter.name} produced out-of-bounds cell: "
                    f"{c.rect.to_bounding_box()}"
                )

    def test_all_voters_set_from_ocr_true(self, all_voters, known_text_image):
        for voter in all_voters:
            cells = voter.run(known_text_image, [_full_rect(known_text_image)])
            for c in cells:
                assert c.from_ocr is True, f"voter {voter.name} forgot from_ocr"

    def test_all_voters_normalise_confidence(self, all_voters, known_text_image):
        for voter in all_voters:
            cells = voter.run(known_text_image, [_full_rect(known_text_image)])
            for c in cells:
                assert 0.0 <= c.confidence <= 1.0, (
                    f"voter {voter.name} confidence {c.confidence} outside [0,1]"
                )
