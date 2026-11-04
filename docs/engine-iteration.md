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

The JSON reference and PDF are separate API observations; a common year does not prove identical submission versions. Treat recovery as diagnostic, not certification. CI retains the live artifact for 30 days. The bounded live-kopi job runs on same-repository PRs; regular fixture evaluation remains deterministic and offline.

## Learning after each OCR run

Each page/engine invocation now appends and flushes progress.jsonl: elapsed seconds, cell count, empty-output status, page recovery, newly recovered document reference values, cumulative recovery and remaining document references. Remaining references are not page-level errors: the API does not tell us which page should contain each value.

Document evaluation unions recoveries from individual pages. Previously, concatenation could construct a false number from the last digits of one page and the first digits of the next. A regression test now rejects this while retaining support for split tokens within a page. Within-page token adjacency still needs spatial validation; integer presence cannot establish table-cell correctness. Empty voter sets cannot imply unanimous recovery.

Use progress and observations together to identify the page and engine needing investigation. Retain a regression case before changing extraction behavior, rerun the fixed fixture and live sample, and compare recovery on the same reference values. This runner records evidence for code iteration; it does not automatically rewrite code or treat OCR agreement as ground truth.

## Spatial evidence diagnostic

After each OCR invocation, spatial-evidence.jsonl records the page, engine, original cell-list indices, text, bounding box and recovered reference integers. progress.jsonl compares these spatially supported hits with page-text recovery. The final evaluation lists values requiring spatial review per engine.

The diagnostic combines cells only when their vertical overlap is at least half the larger height and the horizontal gap is nonnegative and at most 1.5 times the smaller height. Short standalone minus/parenthesis tokens use half the smaller height for vertical overlap and the larger height for the gap bound. A live TSV observation for organisation 813322072 exposed a seven-pixel-high minus beside a 35-pixel-high `864`; the initial rule incorrectly separated them. Its exact geometry is now a regression fixture, including the adjacent column to guard against joining unrelated amounts. These are explicit conservative heuristics, not calibrated probabilities. Original OCR output remains unchanged. A single OCR cell can itself contain multiple rows or columns; geometry cannot separate its internal text. Within-cell numeric matching also retains the existing whitespace-tolerant matcher. Therefore spatial support is diagnostic, not certification of the financial concept or table cell.

This iteration preserves the established recovery metric while adding traceable evidence and an investigation queue. Evaluate disagreement on saved observations before promoting the diagnostic to an acceptance gate. No early stopping occurs when reference values have been found: later pages contain notes outside the financial API's ground truth.
