# regnskapsnoter

Personal side project. Document-AI pipeline for Norwegian årsregnskap (annual financial statements):
multi-DGP OCR cascade + XBRL-style taxonomy + W3C Web Annotation emission, glued together via Docling.

## What it does

```
PDF → cascade OCR (7 voters, vote-at-query-time)
    → Docling layout + TableFormer
    → noter-canonicalizer (label → regnskap-no:* concept ID)
    → WADM JSON-LD annotations (bbox + concept + value + cascade confidence)
    → SHACL validation (calc arcs, period attributes, axis members)
```

## Packages

| Package | What |
|---|---|
| `docling-cascade-ocr` | `BaseOcrModel` plugin: 7-voter cascade with `xalign_vote` column-drop veto |
| `regnskap-no` | Wheel of the [`regnskapnoter-taxonomy`](https://github.com/sondreskarsten/regnskapnoter-taxonomy) build artifacts (279 concepts, 4 axes, 97 calc arcs) |
| `noter-canonicalizer` | exact → fuzzy → embedding label resolution |
| `regnskapsnoter-wadm` | W3C WADM emitter with `registrum:*` namespaced extensions for cascade + XBRL attrs |
| `regnskapsnoter-shacl` | Fact-level validation: calc arcs, period attrs, axis members |
| `regnskapsnoter-pipeline` | Per-leaf-type Docling configs + enrichment chain |

## Tests

76 unit tests across 6 packages — all passing. End-to-end smoke test on a real
v2-fixture PDF produces 43 WADM annotations of which 38 pass SHACL validation.

## License

MIT (this monorepo). The `regnskap-no` taxonomy artifacts are CC-BY-4.0.
