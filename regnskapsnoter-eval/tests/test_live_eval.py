"""Live eval test against the v2 fixture.

This test runs the actual cascade against ONE BRREG fixture PDF and verifies
the eval harness produces a non-trivial number of reliable hits. It's the
end-to-end smoke that protects audit finding D5 (the central reliability
claim is reproducible).

Gated on:

- ``REGNSKAPSNOTER_LIVE_EVAL=1`` env var (opt-in; live runs are slow)
- Tesseract + Norwegian language data
- PyMuPDF (fitz) for rendering
- google-cloud-storage credentials with read access to ``sondre_brreg_data``
"""
from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest


SKIP_REASON = (
    "Live eval requires REGNSKAPSNOTER_LIVE_EVAL=1 + Tesseract + PyMuPDF + GCS creds"
)


def _env_ok() -> bool:
    if os.environ.get("REGNSKAPSNOTER_LIVE_EVAL") != "1":
        return False
    try:
        import pytesseract  # noqa
        import fitz  # noqa
        from google.cloud import storage  # noqa
    except ImportError:
        return False
    if not Path(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    ).is_file():
        return False
    return True


@pytest.mark.skipif(not _env_ok(), reason=SKIP_REASON)
def test_live_cascade_recovers_brreg_truth_for_one_fixture(tmp_path):
    """Run two real voters against one v2 fixture; assert ≥ 5/7 truth values reliable."""
    from google.cloud import storage as gcs
    from google.oauth2 import service_account
    import fitz
    from PIL import Image

    from docling_core.types.doc import BoundingBox, CoordOrigin
    from docling_cascade_ocr.voters import TesseractVoter, TesseractTsvVoter
    from regnskapsnoter_eval import (
        load_truth_from_local,
        score_consensus,
        truth_numbers,
    )

    # Download the smallest fixture (Fana, 6 pages)
    creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = service_account.Credentials.from_service_account_file(creds_path)
    client = gcs.Client(project=creds.project_id, credentials=creds)
    pdf_path = tmp_path / "fixture.pdf"
    client.bucket("sondre_brreg_data").blob(
        "raw/ocr_eval_v2_10pdfs_300dpi/fixture/pdfs/811602892.pdf"
    ).download_to_filename(str(pdf_path))
    assert pdf_path.exists()

    # Render page-by-page at 150 DPI (memory-bounded)
    v1 = TesseractVoter(lang=["no", "nb"])
    v2 = TesseractTsvVoter(lang=["no", "nb"])
    per_voter_cells = {"tesseract": [], "tesseract_tsv": []}

    doc = fitz.open(str(pdf_path))
    for p in range(doc.page_count):
        pix = doc[p].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        rect = BoundingBox(l=0, t=0, r=img.width, b=img.height,
                            coord_origin=CoordOrigin.TOPLEFT)
        per_voter_cells["tesseract"] += v1.run(img, [rect])
        per_voter_cells["tesseract_tsv"] += v2.run(img, [rect])
        img.close()
        gc.collect()
    doc.close()

    # Truth + reliability check
    truth_dir = (
        Path(__file__).parent / "data" / "brreg_ground_truth"
    )
    truth = load_truth_from_local(truth_dir)
    nums = truth_numbers(truth, drop_zero=True)
    fana_truth = nums["811602892"]

    reports = score_consensus(
        orgnr="811602892",
        per_voter_cells=per_voter_cells,
        truth=fana_truth,
        min_voters_for_reliable=2,  # 2 of 2 voters
    )

    n_reliable = sum(1 for r in reports if r.reliable)
    n_universal_miss = sum(1 for r in reports if r.n_hit == 0)

    # The reproducible claim from the v2 audit is that on 7-voter production
    # the fixture is 99/100 reliable. Here with only 2 voters, we still
    # expect MOST values to be recovered. Tighten this when more voters
    # become available in CI.
    assert n_reliable >= max(1, len(reports) - 2), (
        f"Only {n_reliable}/{len(reports)} truth values reliable on Fana fixture. "
        f"Universal-miss: {n_universal_miss}. Reports: "
        + ", ".join(f"{r.truth_value}({r.n_hit}/{r.n_attempted})" for r in reports)
    )
    assert n_universal_miss == 0, (
        f"{n_universal_miss} truth values were missed by all voters — "
        "this should never happen on the Fana fixture per the v2 audit."
    )
