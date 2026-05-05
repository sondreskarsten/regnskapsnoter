# regnskapsnoter-pipeline

End-to-end Docling pipeline for Norwegian årsregnskap. Orchestrates:

- `docling-cascade-ocr` — multi-DGP voting at the OCR layer
- `regnskap-no` — taxonomy lookup
- `noter-canonicalizer` — label → concept-ID resolution
- `regnskapsnoter-wadm` — W3C Web Annotation emission
- `regnskapsnoter-shacl` — fact-level validation

## Per-leaf-type configs

```python
from regnskapsnoter_pipeline import get_config, RegnskapsnoterPipeline

# Direct factory access
opts = get_config("brreg_template")

# Or use the high-level pipeline
pipe = RegnskapsnoterPipeline(leaf_type="brreg_template",
                               audit_ledger_path="/var/log/cascade.jsonl")
out = pipe.convert("path/to/aarsregnskap.pdf", period_end="2024-12-31")

print(out.enrichment.n_facts_emitted)
print(out.enrichment.validation.conforms)
```

## Leaf types

- `brreg_template` — BRREG-rasterised PDFs (most common)
- `konsernregnskap` — consolidated regnskap, stricter validation
- `auditor_report` — revisjonsberetning, prose-heavy
- `tx_log` — transaction log dumps, dense numerics

## License

MIT
