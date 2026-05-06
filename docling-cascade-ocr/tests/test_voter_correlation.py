"""Voter independence tests (validation plan item 3).

Empirical finding: docling_default (psm 3) and tesseract (psm 6) produce
0.952 Jaccard similarity on numeric tokens from the Fana fixture (60
pages at 150 DPI). They share the same Tesseract engine with nearly
identical configuration; the psm difference barely matters on clean
bank-template PDFs.

These tests verify:

1. The default voter_groups in CascadeOcrOptions marks tesseract +
   docling_default as a correlated group.
2. CascadeSummary.effective_n_voters counts that group as 1.
3. The empirical correlation is documented via an explicit assertion
   on the fixture data (so a future Docling change that makes the
   voters genuinely independent would fail this test and prompt an
   update to voter_groups).
"""
from __future__ import annotations

import gc
import re
from itertools import combinations
from pathlib import Path

import pytest

from docling_cascade_ocr.summary import CascadeSummary


# ---- voter_groups config ----

def test_default_voter_groups_contains_tesseract_docling_default():
    from docling_cascade_ocr.options import CascadeOcrOptions
    opts = CascadeOcrOptions()
    flat = [name for group in opts.voter_groups for name in group]
    assert "tesseract" in flat
    assert "docling_default" in flat


def test_effective_n_voters_with_default_groups():
    """With the default group [tesseract, docling_default], effective
    count should be n_voters - 1 (since the group of 2 counts as 1)."""
    s = CascadeSummary()
    s.voters_attempted = ["tesseract", "tesseract_tsv", "docling_default"]
    s.n_voters = 3
    s.voter_groups = [["tesseract", "docling_default"]]
    # Group of 2 counts as 1, tesseract_tsv counts as 1 → effective = 2
    assert s.effective_n_voters == 2


def test_effective_n_voters_no_groups_equals_n_voters():
    s = CascadeSummary()
    s.voters_attempted = ["a", "b", "c"]
    s.n_voters = 3
    s.voter_groups = []
    assert s.effective_n_voters == 3


def test_effective_n_voters_group_member_not_present():
    """If a group member wasn't actually used (e.g. docling_default not
    installed), the group doesn't count unless ≥1 member is present."""
    s = CascadeSummary()
    s.voters_attempted = ["tesseract", "paddleocr"]
    s.n_voters = 2
    s.voter_groups = [["tesseract", "docling_default"]]
    # tesseract is in the group (alone, but still a group hit) → group = 1
    # paddleocr is ungrouped → 1
    # effective = 2
    assert s.effective_n_voters == 2


def test_effective_n_voters_multiple_groups():
    s = CascadeSummary()
    s.voters_attempted = ["a", "b", "c", "d", "e"]
    s.n_voters = 5
    s.voter_groups = [["a", "b"], ["c", "d"]]
    # Group 1 (a, b) = 1, Group 2 (c, d) = 1, e = 1 → effective = 3
    assert s.effective_n_voters == 3


def test_effective_n_voters_in_to_dict():
    s = CascadeSummary()
    s.voters_attempted = ["tesseract", "tesseract_tsv", "docling_default"]
    s.n_voters = 3
    s.voter_groups = [["tesseract", "docling_default"]]
    d = s.to_dict()
    assert d["n_voters"] == 3
    assert d["effective_n_voters"] == 2
    assert d["voter_groups"] == [["tesseract", "docling_default"]]


# ---- Empirical correlation assertion on Fana fixture ----

def _has_pil_and_tesseract():
    try:
        from PIL import ImageFont
        ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        import pytesseract
        pytesseract.get_languages()
        return True
    except Exception:
        return False


def _extract_numbers(text):
    text = text.replace('\u2212', '-').replace('\u2013', '-')
    cleaned = re.sub(r'(?<=\d)[\s\u00a0\u202f]+(?=\d)', '', text)
    nums = set()
    for m in re.finditer(r'-?\d+', cleaned):
        v = int(m.group())
        if abs(v) >= 10:
            nums.add(v)
    return nums


@pytest.mark.skipif(
    not _has_pil_and_tesseract(),
    reason="PIL + Tesseract required",
)
def test_tesseract_psm6_and_docling_default_are_empirically_correlated():
    """Asserts that the two voters produce Jaccard > 0.90 on the Fana
    fixture. If this test fails, it means a Tesseract or Docling update
    has made them genuinely different — reconsider voter_groups."""
    from PIL import Image
    from docling_core.types.doc import BoundingBox, CoordOrigin
    from docling_cascade_ocr.voters import TesseractVoter, DoclingDefaultVoter

    raster_dir = Path(__file__).parent / "data" / "rasters"
    if not (raster_dir / "811602892_page01.png").exists():
        # Rasters are in regnskapsnoter-eval, not cascade. Try there.
        raster_dir = Path(__file__).parents[2] / "regnskapsnoter-eval" / "tests" / "data" / "rasters"
    if not (raster_dir / "811602892_page01.png").exists():
        pytest.skip("Fana fixture rasters not found")

    psm6 = TesseractVoter(lang=["no", "nb"])
    psm3 = DoclingDefaultVoter(lang=["no", "nb"])

    nums_psm6 = set()
    nums_psm3 = set()
    for p in range(1, 7):
        img = Image.open(raster_dir / f"811602892_page{p:02d}.png")
        rect = BoundingBox(l=0, t=0, r=float(img.width), b=float(img.height),
                           coord_origin=CoordOrigin.TOPLEFT)
        for c in psm6.run(img, [rect]):
            nums_psm6.update(_extract_numbers(c.text))
        for c in psm3.run(img, [rect]):
            nums_psm3.update(_extract_numbers(c.text))
        img.close()
        gc.collect()

    intersection = nums_psm6 & nums_psm3
    union = nums_psm6 | nums_psm3
    jaccard = len(intersection) / len(union) if union else 0.0

    assert jaccard > 0.90, (
        f"tesseract (psm 6) and docling_default (psm 3) Jaccard = {jaccard:.3f} "
        f"on Fana fixture — below 0.90. If the voters have become genuinely "
        f"independent, remove them from voter_groups in CascadeOcrOptions."
    )
