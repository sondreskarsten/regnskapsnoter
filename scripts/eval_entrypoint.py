#!/usr/bin/env python3
"""Eval entrypoint for Cloud Run Job.

MODE env var controls which evaluation runs:
  MODE=production_eval   → Item 4: all 7 voters on 10 fixtures, threshold=5
  MODE=docling_eval      → Item 6: CascadePredictionProvider through OcrEvaluator
"""
import gc
import json
import os
import sys
import time
import re

from google.cloud import storage as gcs
from google.oauth2 import service_account

BUCKET = "sondre_brreg_data"
FIXTURE_PREFIX = "raw/ocr_eval_v2_10pdfs_300dpi/fixture/pdfs/"

def get_client():
    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key and os.path.exists(key):
        creds = service_account.Credentials.from_service_account_file(key)
        return gcs.Client(credentials=creds, project=creds.project_id)
    return gcs.Client()


def run_production_eval():
    """Item 4: run all available voters on 10 fixtures, score at threshold=5."""
    import fitz
    from PIL import Image
    from docling_core.types.doc import BoundingBox, CoordOrigin

    from docling_cascade_ocr.voters.base import build_voters
    from docling_cascade_ocr.options import CascadeOcrOptions

    opts = CascadeOcrOptions()
    # Build all enabled voters
    voters = build_voters(
        [v for v in opts.voters if v.enabled],
        lang=opts.lang, use_gpu=False,
    )
    print(f"Loaded {len(voters)} voters: {[v.name for v in voters]}")

    client = get_client()
    bucket = client.bucket(BUCKET)

    def extract_numbers(text):
        text = text.replace('\u2212', '-').replace('\u2013', '-')
        cleaned = re.sub(r'(?<=\d)[\s\u00a0\u202f]+(?=\d)', '', text)
        nums = set()
        for m in re.finditer(r'-?\d+', cleaned):
            v = int(m.group())
            if abs(v) >= 100:
                nums.add(v)
        return nums

    results = []
    for blob in client.list_blobs(bucket, prefix=FIXTURE_PREFIX):
        if not blob.name.endswith('.pdf'):
            continue
        orgnr = blob.name.split('/')[-1].replace('.pdf', '')
        local = f'/tmp/{orgnr}.pdf'
        blob.download_to_filename(local)

        doc = fitz.open(local)
        n_pages = doc.page_count
        per_voter = {v.name: set() for v in voters}

        for p_idx in range(n_pages):
            pix = doc[p_idx].get_pixmap(matrix=fitz.Matrix(150/72, 150/72))
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            rect = BoundingBox(l=0, t=0, r=float(img.width), b=float(img.height),
                               coord_origin=CoordOrigin.TOPLEFT)
            for voter in voters:
                try:
                    cells = voter.run(img, [rect])
                    for c in cells:
                        per_voter[voter.name].update(extract_numbers(c.text))
                except Exception as e:
                    print(f"  {voter.name} failed on {orgnr} p{p_idx}: {e}")
            img.close()
            gc.collect()
        doc.close()

        # Count tokens seen by >=5 voters (threshold)
        all_tokens = set()
        for nums in per_voter.values():
            all_tokens |= nums
        threshold = min(5, len(voters))
        reliable = 0
        for token in all_tokens:
            hits = sum(1 for v in voters if token in per_voter[v.name])
            if hits >= threshold:
                reliable += 1

        results.append({
            "orgnr": orgnr,
            "n_pages": n_pages,
            "n_voters": len(voters),
            "n_tokens_total": len(all_tokens),
            "n_tokens_reliable_at_5": reliable,
            "per_voter_token_counts": {v.name: len(per_voter[v.name]) for v in voters},
        })
        print(f"  {orgnr}: {len(all_tokens)} tokens, {reliable} reliable at threshold={threshold}")

    # Save
    import pyarrow as pa, pyarrow.parquet as pq
    out_path = f"raw/cascade_eval_production/results.json"
    bucket.blob(out_path).upload_from_string(
        json.dumps(results, indent=2), content_type="application/json")
    print(f"\nResults → gs://{BUCKET}/{out_path}")


def run_docling_eval():
    """Item 6: CascadePredictionProvider through docling-eval's OcrEvaluator."""
    print("docling-eval end-to-end not yet implemented in Cloud Run")
    print("Requires: build DatasetRecord per fixture, run predict(), evaluate")
    # Placeholder for the docling-eval integration
    # This is the OOM-risky path; fallback: cascade-only mode
    sys.exit(0)


if __name__ == "__main__":
    mode = os.environ.get("MODE", "production_eval")
    print(f"Eval entrypoint: MODE={mode}")
    if mode == "production_eval":
        run_production_eval()
    elif mode == "docling_eval":
        run_docling_eval()
    else:
        print(f"Unknown MODE: {mode}")
        sys.exit(1)
