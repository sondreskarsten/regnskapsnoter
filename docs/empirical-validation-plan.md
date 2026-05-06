# Empirical Validation Plan

Closes every gap identified in the critical review of audit delivery.
Seven work items, ordered by dependency chain (later items consume
outputs from earlier ones). Each item names: the gap, the concrete
task, the acceptance criterion, and the infrastructure.

---

## 1. Vertex AI integration test (C2 + C7 gate)

**Gap.** `GeminiClient.__call__` and `DocumentAiVoter._call_vertex` have
never been called against Vertex AI. Request body shape, response
parsing, error handling are all unverified.

**Task.** Deploy a Cloud Run Job `regnskapsnoter-vertex-test` that:

1. Loads the 10 v2 fixture PDFs from
   `gs://sondre_brreg_data/raw/ocr_eval_v2_10pdfs_300dpi/fixture/pdfs/`.
2. For each PDF, renders page 4 (the balanse page) at 150 DPI.
3. Calls `DocumentAiVoter._call_vertex` on the page image and records
   the response text.
4. Calls `GeminiClient.__call__` with the `pydantic_for_calc_arc`
   schema for `regnskap-no:Eiendeler` / `[620000] Balanse` against
   the OCR text, records the parsed JSON.
5. Scores both outputs against BRREG nøkkeltall truth (fetched live
   from `https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}`).
6. Writes a results parquet to
   `gs://sondre_brreg_data/raw/vertex_integration_test/results.parquet`
   and the extraction code alongside it.

**Acceptance criterion.**

- ≥ 8 of 10 fixture orgnrs: `DocumentAiVoter` response text contains
  the BRREG truth value for Sum eiendeler (number_present match).
- ≥ 8 of 10 fixture orgnrs: `GeminiClient` extract JSON contains a
  non-null `anleggsmidler` field.
- Zero unhandled exceptions; any HTTP 4xx/5xx is caught and logged,
  not crashed.
- Response envelope parsing (candidates → content → parts → text)
  matches the actual Vertex AI return shape.

**Infrastructure.**

- Cloud Run Job: `europe-north1`, 2 vCPU / 4 GiB, 600s timeout.
- Vertex AI: `us-central1` endpoint, `gemini-2.5-flash`,
  `thinkingBudget: 0`, `temperature: 0.0`.
- Service account: `s1sfreracct@sondreskarsten-d7d14.iam.gserviceaccount.com`
  (already has Vertex AI User role).
- Image: extend `europe-north1-docker.pkg.dev/.../brreg-pipelines/`
  with a `regnskapsnoter-vertex-test` image. Base FROM python:3.12-slim,
  `pip install regnskapsnoter-xbrl regnskap-no PyMuPDF google-auth
  requests`.

**What this proves.** That the request body shape, auth flow,
thinkingBudget config, response parsing, and error handling all work
end-to-end against real Vertex AI. No mock. This is the first-ever
production call for both C2 and C7 code paths.

---

## 2. Arelle validation of iXBRL output (C6 gate)

**Gap.** The `schemaRef` points at a URL that doesn't exist. No
validator has ever consumed the output.

**Task.** Two-part fix:

**Part A — Host the schema.** Build a minimal XSD at
`regnskap-no/src/regnskap_no/data/regnskap-no.xsd` that declares the
279 concepts as `xbrli:item` elements with their `periodType` and
`balance` attributes. This is a machine-generated file from the
taxonomy parquet. Ship it in the wheel under `data/`. Update
`schemaRef` default to a `file:///` path or a raw GitHub URL
(`https://raw.githubusercontent.com/sondreskarsten/regnskapsnoter/main/regnskap-no/src/regnskap_no/data/regnskap-no.xsd`).

**Part B — Run Arelle.** Install `arelle-release` (`pip install
arelle-release`). Build iXBRL for 3 test orgnrs from the v2 fixture
(using BRREG nøkkeltall as values). Run:

```python
from arelle import ModelManager, Cntlr
ctrl = Cntlr.Cntlr()
mm = ctrl.modelManager
mm.load(ixbrl_path)
errors = [e for e in mm.modelXbrl.errors]
```

**Acceptance criterion.**

- Arelle loads the document without schema-resolution errors.
- All `ix:nonFraction` facts resolve to a declared concept in the XSD.
- Context/unit references resolve.
- The `sign` attribute on negative values is accepted.
- 0 Arelle errors on a document with 10+ balanced facts (parent =
  sum of children).

**Infrastructure.** Runs in this chat or in CI. No Cloud Run needed.
`arelle-release` is a pip install. The XSD generation script runs
against the taxonomy parquet already in the wheel.

**What this proves.** That the iXBRL output is not just structurally
well-formed XML, but spec-compliant iXBRL 1.1 that a real validator
accepts.

---

## 3. Voter independence fix (C1 design flaw)

**Gap.** Three of nine default voters (`tesseract` psm 6,
`tesseract_tsv` word-level, `docling_default` psm 3) all run
pytesseract on the same Tesseract installation. Under the "each
voter = separate DGP" principle they share the same underlying engine,
producing correlated outputs. Vote-share confidence is upward-biased.

**Task.**

1. **Empirical measurement** first, not a code change. Run all three
   pytesseract voters on the 10 v2 fixture PDFs (60 pages). For each
   numeric token extracted by at least one voter, record which voters
   saw it. Compute:

   - Pairwise agreement rate between the three pytesseract voters
   - Pairwise agreement rate between each pytesseract voter and the
     non-tesseract voters (paddleocr, doctr, easyocr, ocrmypdf)
   - If the pytesseract-triplet pairwise rate is > 0.95 while the
     cross-engine rate is < 0.85, the correlation is real and material.

2. **If correlation is confirmed:** change the default voter list.
   Options (pick one):

   a. Drop `tesseract_tsv` from defaults (keep `tesseract` psm 6 +
      `docling_default` psm 3 as the two "Tesseract observations").
   b. Replace `docling_default` with a `tesserocr` binding (Docling's
      actual stock OCR), making it genuinely independent at the C-level.
   c. Weight the three pytesseract voters as 1/3 each in the vote
      (i.e. they collectively count as one vote, not three).

3. **Update `CascadeSummary.fraction_clusters_unanimous`** to report
   "effective independent voter count" alongside the raw count. Add a
   `voter_groups` attribute: `[["tesseract", "tesseract_tsv",
   "docling_default"], ["paddleocr"], ["doctr"], ...]` so downstream
   consumers can compute independence-adjusted confidence.

**Acceptance criterion.**

- Pairwise correlation table committed to
  `gs://sondre_brreg_data/raw/voter_correlation/pairwise.parquet`.
- If correlation > 0.95: default voter list updated, tests updated,
  vote-share confidence no longer inflated.
- If correlation < 0.85: document the finding and leave the config
  unchanged.

**Infrastructure.** Run in this chat against the committed fixtures
(already in the repo; no GCS access needed for the measurement).

---

## 4. Production-strength empirical threshold (B2/D5 gate)

**Gap.** The CI test uses `min_voters_for_reliable = max(1, n_voters - 1)`.
With 2 Tesseract voters that resolves to 1 — any single voter agreeing
is "reliable." The original v2 audit claimed "6 of 7 voters agreed."

**Task.**

1. **Deploy a Cloud Run Job `regnskapsnoter-eval-production`** that:

   a. Installs all 7 production voters (Tesseract, TesseractTsv,
      ocrmypdf, PaddleOCR, doctr, EasyOCR, docling_default).
   b. Runs the cascade against all 10 v2 fixture PDFs (60 pages).
   c. Scores with `min_voters_for_reliable = 5` (majority of 7).
   d. Writes per-orgnr, per-truth-value, per-voter hit/miss to
      `gs://sondre_brreg_data/raw/cascade_eval_production/results.parquet`.

2. **Lock in the CI threshold.** After the production run establishes
   the real number (e.g. "47/47 truth values reliable at threshold=5"),
   update the committed CI test with a `PRODUCTION_THRESHOLD` constant
   that reflects the empirical bar, not the "max(1, n-1)" formula.
   The CI test with 2 voters keeps running at threshold=1 but adds
   a comment: "Production bar is threshold=5 on 7 voters; see
   gs://...results.parquet."

**Acceptance criterion.**

- Cloud Run Job completes on all 10 PDFs without OOM (requires
  ≥ 8 GiB; PaddleOCR + doctr + EasyOCR are memory-hungry).
- 0 universal misses at threshold=5.
- ≥ 90% of truth values reliable at threshold=5.
- Results parquet committed to GCS with the extraction script.

**Infrastructure.**

- Cloud Run Job: `europe-north1`, 4 vCPU / 16 GiB, 3600s timeout.
- Docker image: extend `r-base:latest` or build a new Python image
  with all 7 OCR engines pre-installed.
- The 10 fixture PDFs are already in
  `gs://sondre_brreg_data/raw/ocr_eval_v2_10pdfs_300dpi/fixture/pdfs/`.

---

## 5. Migration tooling on real corpus (C11 gate)

**Gap.** `diff_facts` has been tested on 3 synthetic Facts. The audit
asked for the 18,924-PDF corpus. We have 12,879 v1 noter extraction
JSONs in `gs://sondre_brreg_data/raw/noter_extraction_2025/raw/`.

**Task.**

1. **Parse v1 facts.** Write a `v1_adapter.py` that reads a v1 Gemini
   extraction JSON (`{orgnr}_aarsregnskap_{year}_v2.json`) and returns
   a list of `Fact(orgnr, concept_id, value, period_end, source="v1")`.
   The v1 JSONs have varying schemas per NACE code; the adapter reads
   whatever numeric fields are present and attempts label resolution
   via `noter-canonicalizer.resolve()` to map to regnskap-no concept
   IDs.

2. **Build v2 facts from BRREG nøkkeltall.** For each orgnr in the v1
   corpus, fetch structured nøkkeltall from
   `https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}` or
   from `finstat.parquet`. Emit `Fact(..., source="brreg")`.

3. **Run diff_facts(v1, brreg).** This isn't v1-vs-v2-cascade; it's
   v1-vs-ground-truth. The more useful migration metric: how often
   did the Gemini prompt agree with BRREG's own published nøkkeltall?

4. **Write results.** `per_concept_drift` + `per_orgnr_summary` +
   `write_diff_parquet` to
   `gs://sondre_brreg_data/raw/migration_v1_vs_brreg/`.

**Acceptance criterion.**

- ≥ 5,000 v1 extraction JSONs parsed (of 12,879 total; the rest may
  fail on schema variation — record the failure rate).
- Agreement rate per concept computed for every concept that appears
  in ≥ 10 orgnrs.
- Concept-level drift table shows the expected pattern: near-perfect
  agreement on Sum eiendeler / Sum gjeld (v1 gets these right),
  lower agreement on sub-items (where v1's Gemini prompt drops
  values).
- Results parquet + adapter code committed to GCS.

**Infrastructure.**

- Run in this chat (BRREG nøkkeltall API is public, no auth needed).
- For the full 12,879 files, paginate in batches of 500; each batch
  takes ~30s for the label resolution.
- `finstat.parquet` (918 MB) is in `gs://firm-deterioration/` as a
  faster alternative to 12,879 individual API calls.

---

## 6. docling-eval end-to-end (C4 gate)

**Gap.** `CascadePredictionProvider` is wired but `OcrEvaluator` has
never been run through it on a real fixture.

**Task.**

1. Build a minimal `DatasetRecord` for each of the 10 v2 fixture PDFs.
   Ground truth: build `DoclingDocument` objects from the BRREG
   nøkkeltall (text items = the labels, tables = the values). This is
   an approximation — docling-eval's `OcrEvaluator` compares text
   content, not structured facts.

2. Run `CascadePredictionProvider.predict()` on each record. This
   triggers the full Docling pipeline including cascade OCR.

3. Feed the (ground_truth, prediction) pairs to
   `docling_eval.evaluators.ocr_evaluator.OcrEvaluator`.

4. Report the metrics docling-eval produces (CER, WER, etc.) and
   write them to
   `gs://sondre_brreg_data/raw/docling_eval_cascade/metrics.json`.

**Acceptance criterion.**

- All 10 predictions complete (status = SUCCESS, not FAILURE).
- OcrEvaluator produces CER < 0.05 on the Fana fixture (we know
  Tesseract is >95% accurate on this clean bank-template PDF).
- Results committed to GCS with the extraction code.

**Infrastructure.**

- Cloud Run Job: `europe-north1`, 4 vCPU / 16 GiB, 3600s timeout.
  The full Docling pipeline (layout model + TableFormer) needs ~4–6 GB.
  If OOM, fall back to cascade-only mode (skip TableFormer, disable
  `do_table_structure`).
- Docker image: needs `docling[full]` + `docling-eval` + all 7 voters.
  Build as `regnskapsnoter-eval-full`.

**Risk.** High — Docling's full pipeline OOMs at 4 GiB in previous
tests. The fallback (cascade-only, no TableFormer) is acceptable for
the C4 gate because the audit asked "can docling-eval *consume* our
provider?" not "does TableFormer work?"

---

## 7. PyPI first release (C14 gate)

**Gap.** Nothing is published. `pip install regnskap-no` fails.

**Task.**

1. Create a PyPI account for Sondre Skarsten.
2. Create API tokens: one scoped to `regnskap-no`, one to
   `noter-canonicalizer`, one to `regnskapsnoter-xbrl`, one to
   `regnskapsnoter-migration`. (Or one project-scoped token per
   package.)
3. Add `PYPI_API_TOKEN` to the GitHub repo secrets.
4. Tag `v1.0.3` and push: `git tag v1.0.3 && git push origin v1.0.3`.
5. Verify the workflow triggers, builds, and uploads.
6. Verify: `pip install regnskap-no==1.0.3` in a fresh venv on a
   different machine.

**Acceptance criterion.**

- `pip install regnskap-no` succeeds from PyPI.
- `pip install noter-canonicalizer` pulls `regnskap-no` as a
  dependency.
- `pip install regnskapsnoter-xbrl` and
  `pip install regnskapsnoter-migration` both install cleanly.
- Package pages on pypi.org render the README markdown correctly.

**Infrastructure.** PyPI account + GitHub Actions (already wired in
`.github/workflows/publish.yml`).

**Dependency.** This is the only item that requires Sondre's personal
action (account creation + secrets). Everything else can be done
autonomously.

---

## Execution order

```
   ┌─────────────────────────────────┐
   │ 1. Vertex AI integration test   │ ← unblocks empirical confidence
   │    (C2 + C7)                    │   in DocumentAi + GeminiClient
   └────────────┬────────────────────┘
                │
   ┌────────────▼────────────────────┐
   │ 2. Arelle iXBRL validation      │ ← unblocks "spec-compliant" claim
   │    (C6)                         │   (XSD generation + Arelle run)
   └────────────┬────────────────────┘
                │
   ┌────────────▼────────────────────┐
   │ 3. Voter correlation test       │ ← can run immediately (fixtures
   │    (C1 independence)            │   in repo), informs #4 threshold
   └────────────┬────────────────────┘
                │
   ┌────────────▼────────────────────┐
   │ 4. Production eval Cloud Run    │ ← depends on #3 (voter list may
   │    (B2/D5 threshold)            │   change), needs all 7 engines
   └────────────┬────────────────────┘
                │
   ┌────────────▼────────────────────┐
   │ 5. Migration v1 → BRREG diff    │ ← runs in chat, uses finstat.pq
   │    (C11 real corpus)            │   + noter_extraction_2025 JSONs
   └────────────┬────────────────────┘
                │
   ┌────────────▼────────────────────┐
   │ 6. docling-eval end-to-end      │ ← Cloud Run with full Docling;
   │    (C4)                         │   fallback: cascade-only mode
   └────────────┬────────────────────┘
                │
   ┌────────────▼────────────────────┐
   │ 7. PyPI publish                 │ ← requires Sondre's PyPI account;
   │    (C14)                        │   everything else is automated
   └─────────────────────────────────┘
```

Items 1–3 can execute in parallel. Item 5 can start immediately
(no Cloud Run dependency). Item 7 is decoupled from everything else
but happens last because the final wheel versions should incorporate
any fixes surfaced by items 1–6.

---

## Cost estimate

| Item | Compute | Vertex AI | Time |
|---|---|---|---|
| 1. Vertex test | 1 Cloud Run execution (~5 min) | 10 Gemini calls (~$0.02) | 30 min |
| 2. Arelle | Local / CI only | — | 45 min |
| 3. Voter correlation | Local (committed fixtures) | — | 20 min |
| 4. Production eval | 1 Cloud Run execution (~30 min) | — | 2 hr (Docker build + run) |
| 5. Migration diff | Local (GCS reads) | — | 1 hr |
| 6. docling-eval e2e | 1 Cloud Run execution (~60 min) | — | 3 hr (Docker build + run) |
| 7. PyPI publish | GitHub Actions (free) | — | 15 min |

**Total: ~$0.50 cloud spend, ~8 hours of work.**

---

## Per-item test additions

Each item produces new tests that replace the mock-based tests with
empirical assertions:

| Item | Test added | Replaces/strengthens |
|---|---|---|
| 1 | `test_vertex_integration_10_fixtures.py` | C2 mock, C7 mock |
| 2 | `test_arelle_validates_ixbrl.py` | C6 XML-structure-only tests |
| 3 | `test_voter_pairwise_correlation.py` | C1 "psm differs" test |
| 4 | `test_production_eval_threshold.py` | B2/D5 loose threshold |
| 5 | `test_migration_v1_vs_brreg.py` | C11 synthetic-only test |
| 6 | `test_docling_eval_cascade.py` | C4 info/format/missing-PDF tests |
| 7 | — (manual verification) | C14 twine-check-only test |

After all 7 items: the test suite will contain both the fast mock-based
CI tests (always run, ~60s total) AND opt-in empirical tests gated on
`REGNSKAPSNOTER_INTEGRATION=1` or Cloud Run environment (run on demand,
~30 min total, require GCS + Vertex AI access).
