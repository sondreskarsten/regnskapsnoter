"""End-to-end demo: PDF → DoclingDocument → WADM-annotated, SHACL-validated facts.

Targets the canonical v2 fixture at
``gs://sondre_brreg_data/raw/ocr_eval_v2_10pdfs_300dpi/fixture/pdfs/{orgnr}.pdf``
but accepts any file path or URI Docling can read.

Usage:
    python -m scripts.demo \
        --pdf gs://sondre_brreg_data/raw/ocr_eval_v2_10pdfs_300dpi/fixture/pdfs/123456789.pdf \
        --leaf-type brreg_template \
        --period-end 2024-12-31 \
        --out /tmp/demo_out.jsonl
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from regnskapsnoter_pipeline import RegnskapsnoterPipeline
from regnskapsnoter_wadm import write_jsonl, annotations_to_jsonld_collection
import json

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("demo")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf", required=True, help="PDF path or URI")
    p.add_argument("--leaf-type", default="brreg_template",
                   choices=["brreg_template", "konsernregnskap", "auditor_report", "tx_log"])
    p.add_argument("--period-end", default=None, help="ISO date for registrum:periodEnd")
    p.add_argument("--audit-ledger", default=None, help="Optional cascade audit JSONL output")
    p.add_argument("--out", required=True, help="Output JSONL path for WADM annotations")
    p.add_argument("--collection", default=None, help="Optional collection JSON-LD output")
    p.add_argument("--no-fuzzy", action="store_true", help="Disable fuzzy stage in canonicalizer")
    p.add_argument("--use-embedding", action="store_true", help="Enable embedding stage")
    args = p.parse_args()

    pipe = RegnskapsnoterPipeline(
        leaf_type=args.leaf_type,
        audit_ledger_path=args.audit_ledger,
        use_fuzzy=not args.no_fuzzy,
        use_embedding=args.use_embedding,
    )
    log.info("Pipeline ready: leaf_type=%s, voters=%d", args.leaf_type, pipe.cascade_voters_total)

    log.info("Converting %s ...", args.pdf)
    out = pipe.convert(args.pdf, period_end=args.period_end)

    log.info("DoclingDocument ready. texts=%d tables=%d",
             len(getattr(out.document, "texts", []) or []),
             len(getattr(out.document, "tables", []) or []))
    log.info("Enrichment: labels_seen=%d resolved=%d facts=%d",
             out.enrichment.n_labels_seen,
             out.enrichment.n_labels_resolved,
             out.enrichment.n_facts_emitted)

    if out.enrichment.validation is not None:
        v = out.enrichment.validation
        log.info("SHACL/fact validation: conforms=%s passing=%d failing=%d",
                 v.conforms, len(v.passing), len(v.failing))
        for ann, fails in v.failing[:10]:
            for f in fails:
                log.warning("  [%s] %s — %s", f.severity, f.rule, f.message)

    write_jsonl(out.enrichment.annotations, args.out)
    log.info("Wrote %d annotations to %s", out.enrichment.n_facts_emitted, args.out)

    if args.collection:
        coll = annotations_to_jsonld_collection(
            out.enrichment.annotations,
            label=f"Regnskapsnoter facts: {args.pdf}",
        )
        with open(args.collection, "w") as f:
            json.dump(coll, f, ensure_ascii=False, indent=2)
        log.info("Wrote AnnotationCollection to %s", args.collection)

    return 0


if __name__ == "__main__":
    sys.exit(main())
