# docling-cascade-ocr

Multi-DGP OCR voting plugin for [Docling](https://github.com/docling-project/docling).
Treats N OCR engines as N independent observers of the same pixels, votes on
consensus text per cell, and emits Docling `TextCell`s with vote-share confidence.

This plugin is the production fork of the seven-voter cascade originally validated
in [`ocr-cascade-eval`](https://github.com/sondreskarsten/ocr-cascade-eval) (commit
`ffe4d35`) on the v2 fixture (10 Norwegian årsregnskap PDFs, 100 BRREG live-API
truth values, **81/100 unanimous, 99/100 reliable, 0/100 universal-miss**).

## What this is for

Single-engine OCR is unsafe on Norwegian årsregnskap. Three failure modes
combine to produce numbers that look plausible but are wrong:

1. **Column drop** in stacked balance tables — engines that infer rows by
   y-clustering merge two columns into one, returning a numeric value that is the
   sum of two real cells.
2. **Negative-sign mojibake** — ASCII hyphen vs. Unicode minus vs. parenthesised
   negative break a different subset of engines each.
3. **Row-cluster brittleness** — engines that infer rows by clustering
   y-coordinates fail catastrophically on noter pages with interleaved wide
   headers and narrow tables.

This plugin solves the problem by running multiple engines in parallel, voting
per cell, and committing only cells that ≥ 7 out of 10 engines agree on.

## Production verdict

Keep: `ocrmypdf`, `tesseract`, `tesseract_tsv`, `paddleocr`, `doctr`, `easyocr`,
`pix2struct` (lazy tiebreaker).

Drop: `doctr_bbox`, `ocrmypdf_hocr`, `paddleocr_conf` (row-cluster brittle on
stacked balance tables; tripped the column-drop veto so often they contributed
nothing to consensus).

## Install

```bash
pip install docling-cascade-ocr[all]    # all 7 voters
# or selectively:
pip install docling-cascade-ocr[tesseract,easyocr,paddle]
```

System dependencies:
- Tesseract binary with `nor` traineddata (`apt install tesseract-ocr tesseract-ocr-nor`)

## Usage

```python
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_cascade_ocr import CascadeOcrOptions

pipe = PdfPipelineOptions(
    do_ocr=True,
    allow_external_plugins=True,
    ocr_options=CascadeOcrOptions(
        min_voters_for_commit=7,
        column_drop_veto=True,
        audit_ledger_path="/var/log/regnskapsnoter/cascade.jsonl",
    ),
)
converter = DocumentConverter(format_options={
    InputFormat.PDF: PdfFormatOption(pipeline_options=pipe),
})
doc = converter.convert("aarsregnskap.pdf").document
```

## Audit ledger

Set `audit_ledger_path` to write per-page voter outputs and consensus
diagnostics as JSON Lines. Schema mirrors `ocr-cascade-eval`'s
`audit/cascade/v2_10signals/voting.json` so a single downstream auditor can read
both legacy and new outputs.

## How it integrates with Docling

Docling discovers OCR plugins via setuptools entry points under the `docling`
group. This package declares:

```toml
[project.entry-points."docling"]
cascade_ocr = "docling_cascade_ocr"
```

Docling calls `docling_cascade_ocr.ocr_engines()` at import time, which returns
`{"ocr_engines": [CascadeOcrModel]}`. The factory then maps the
`CascadeOcrOptions` discriminator (`kind="cascade"`) to `CascadeOcrModel`.

## Voting algorithm

See `vote.py`. Three-step pipeline:

1. **Cluster cells across voters** by IoU ≥ 0.3 between bounding boxes.
2. **Detect column-drop voters** via x-axis projection and exclude them
   page-wide.
3. **Vote per cluster** on normalised text; commit when `≥ min_voters_for_commit`
   agree.

## Multi-DGP framing

This plugin is the first concrete instance of a reusable pattern: each OCR
engine is a separate Data Generating Process; storing every voter's output as
its own ledger and voting at query time gives an audit trail no single-engine
pipeline can match. See `ocr-cascade-eval/MULTI_DGP_PATTERN.md` for the
generalised principle.

## License

MIT
