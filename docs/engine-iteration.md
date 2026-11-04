# Engine iteration

Run the existing evaluator and inspect the retained evidence before changing extraction thresholds.

```bash
pip install pytest pytesseract Pillow ./regnskap-no ./docling-cascade-ocr ./regnskapsnoter-eval
python -m regnskapsnoter_eval.iterate --raster-dir regnskapsnoter-eval/tests/data/rasters --truth-dir regnskapsnoter-eval/tests/data/brreg_ground_truth --orgnr 811602892 --output iteration
```

Requires Tesseract with Norwegian language data. The output directory must be new. The runner preserves engine-specific words, confidence and coordinates in observations.jsonl; input hashes and package versions in manifest.json; and per-reference-value recovery in evaluation.json. GitHub Actions executes the same command and attaches those files plus pytest results to the run, which identifies the source commit.

The first fixture is six pages from the existing Fana dataset. The two voters share Tesseract; their agreement is not independent evidence. Document integer recovery does not establish correct note, cell, year, unit or concept assignment. Do not use this score as a production acceptance threshold.

The first integration surfaced duplicate taxonomy wheel entries and an incompatible override of Docling's inherited full-page OCR property. Regression cases reject embedded digits, wrong signs and decimal substrings. Subsequent integration must preserve filing identity, accounting context and source-specific observations through taxonomy and reconciliation; the private extraction channels are not yet wired to this runner.

## Live kopi collection

```bash
pip install "./regnskapsnoter-eval[live]"
python -m regnskapsnoter_eval.live --orgnr 811602892 964163006 813322072 --output live-kopi
```

Uses BRREG `/regnskap/aarsregnskap/kopi/{orgnr}/aar` and `/regnskap/aarsregnskap/kopi/{orgnr}/{year}` with the octet-stream Accept header documented by brreg-regnskap. Requests are sequential, paced and retried for transient/rate-limit responses, including HTTP 200 rate-limit bodies. Selects the newest year present in both the raw financial response and available PDF years; `--year` requires an exact match. Multiple submissions for the chosen year are rejected. Original responses, source PDF, receipt timestamps, hashes, all page rasters, OCR observations and evaluation are retained. A 60-page bound rejects larger documents explicitly rather than evaluating a truncated document. Individual failures are retained and the batch returns nonzero while continuing other companies.

The JSON reference and PDF are separate API observations; a common year does not prove identical submission versions. Treat recovery as diagnostic, not certification. CI retains the live artifact for 30 days. The live-kopi job currently runs on this integration PR only; regular fixture evaluation remains deterministic and offline.
