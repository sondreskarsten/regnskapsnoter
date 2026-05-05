# Regnskapsnoter

Personal side project: end-to-end document AI for Norwegian årsregnskap.
Built around [Docling](https://github.com/docling-project/docling) with a
multi-DGP OCR cascade and an XBRL-style noter taxonomy.

> Pixels → multi-voter OCR consensus → typed Docling pipeline → SKOS-resolved
> concepts → W3C Web Annotation facts → SHACL-validated outputs.

This is a *personal initiative* — not affiliated with any employer.

## Architecture

Six packages, one monorepo:

| Package | Role |
|---|---|
| `docling-cascade-ocr` | Multi-DGP OCR voting plugin for Docling. 7 voters, xalign vote, column-drop veto, JSONL audit ledger. |
| `regnskap-no` | Norwegian regnskap noter taxonomy as a Python wheel. 279 concepts, 4 axes, 97 calc arcs, 302 mappings. |
| `noter-canonicalizer` | Resolve observed labels → concept IDs. exact → fuzzy → embedding cascade. |
| `regnskapsnoter-wadm` | W3C Web Annotation Data Model emitter for fact extractions. |
| `regnskapsnoter-shacl` | Fact-level validation: calc-arc consistency, period attributes, dimensional members. |
| `regnskapsnoter-pipeline` | Per-leaf-type Docling configurations + end-to-end orchestration. |

```
                ┌───────────────────────┐
                │ regnskap-no (taxonomy)│   279 concepts, 4 axes, 97 calc arcs
                └─────────┬─────────────┘
                          ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  docling-cascade-ocr  ◄── ocr-cascade-eval (audit ledger schema) │
   └──────────────────────────────────────────────────────────────────┘
                  ▲                                ▲
                  │                                │
                  └──────────┬─────────────────────┘
                             ▼
            ┌──────────────────────────────────┐
            │  noter-canonicalizer             │
            │  exact → fuzzy → embedding       │
            └──────────────┬───────────────────┘
                           ▼
            ┌──────────────────────────────────┐
            │  regnskapsnoter-wadm             │
            │  W3C Web Annotation emission     │
            └──────────────┬───────────────────┘
                           ▼
            ┌──────────────────────────────────┐
            │  regnskapsnoter-shacl            │
            │  Fact-level validation           │
            └──────────────────────────────────┘

         All orchestrated by regnskapsnoter-pipeline.
```

## Quick start

```bash
# Install all six packages locally
pip install -e ./regnskap-no
pip install -e ./docling-cascade-ocr
pip install -e ./noter-canonicalizer[fuzzy]
pip install -e ./regnskapsnoter-wadm
pip install -e ./regnskapsnoter-shacl
pip install -e ./regnskapsnoter-pipeline

# Run the demo on a fixture PDF
python -m scripts.demo \
    --pdf path/to/aarsregnskap.pdf \
    --leaf-type brreg_template \
    --period-end 2024-12-31 \
    --out /tmp/regnskapsnoter_facts.jsonl \
    --collection /tmp/regnskapsnoter_collection.jsonld
```

The demo reads the PDF, runs the multi-DGP cascade, builds a DoclingDocument,
canonicalises the labels against the taxonomy, validates the facts against the
calculation arcs, and writes WADM-conformant JSON-LD output.

## Multi-DGP framing

The `docling-cascade-ocr` plugin is the production fork of the seven-voter
cascade originally validated in
[`ocr-cascade-eval`](https://github.com/sondreskarsten/ocr-cascade-eval).
On the v2 fixture (10 Norwegian årsregnskap PDFs, 100 BRREG live-API truth
values): **81/100 unanimous, 99/100 reliable, 0/100 universal-miss**.

The framing generalises beyond OCR: any layer where N independent observers of
the same latent state are available can use the same audit-ledger-and-vote
pattern. See `ocr-cascade-eval/MULTI_DGP_PATTERN.md`.

## Standards stack (taxonomy)

- **XBRL 2.1** information model (concept attributes, calc arcs, dimensions)
- **SKOS** (prefLabel, altLabel, broader/narrower, mappings)
- **W3C Web Annotation Data Model** for fact emission
- **SHACL + JSON Schema** for validation
- **SemVer 2.0.0** — concept IDs are forever; deprecation never reuses

Authority: regnskapsloven §§ 6-1, 6-1a, 6-2, 7-35 to 7-46 + NRS standards.

## Tests

```
docling-cascade-ocr      22 tests
regnskap-no              12 tests
noter-canonicalizer      11 tests
regnskapsnoter-wadm       9 tests
regnskapsnoter-shacl     12 tests
regnskapsnoter-pipeline  10 tests
─────────────────────────────────
                         76 tests
```

## License

- `regnskap-no` taxonomy: CC-BY-4.0 (matches upstream `regnskapnoter-taxonomy`)
- All other packages: MIT
