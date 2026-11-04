# Engine iteration

Run the existing evaluator and inspect the retained evidence before changing extraction thresholds.

```bash
pip install pytest pytesseract Pillow ./regnskap-no ./docling-cascade-ocr ./regnskapsnoter-eval
python -m regnskapsnoter_eval.iterate --raster-dir regnskapsnoter-eval/tests/data/rasters --truth-dir regnskapsnoter-eval/tests/data/brreg_ground_truth --orgnr 811602892 --output iteration
```

Requires Tesseract with Norwegian language data. The output directory must be new. The runner preserves engine-specific words, confidence and coordinates in observations.jsonl; input hashes and package versions in manifest.json; and per-reference-value recovery in evaluation.json. GitHub Actions executes the same command and attaches those files plus pytest results to the run, which identifies the source commit.

The first fixture is six pages from the existing Fana dataset. The two voters share Tesseract; their agreement is not independent evidence. Document integer recovery does not establish correct note, cell, year, unit or concept assignment. Do not use this score as a production acceptance threshold.

The first integration surfaced duplicate taxonomy wheel entries and an incompatible override of Docling's inherited full-page OCR property. Regression cases reject embedded digits, wrong signs and decimal substrings. Subsequent integration must preserve filing identity, accounting context and source-specific observations through taxonomy and reconciliation; the private extraction channels are not yet wired to this runner.
