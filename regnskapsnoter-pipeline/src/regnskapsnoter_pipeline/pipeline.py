"""End-to-end Regnskapsnoter pipeline.

Glues together:

- Docling's ``DocumentConverter`` with a per-leaf-type ``PdfPipelineOptions``
- ``docling-cascade-ocr`` for multi-DGP voting at the OCR layer
- ``noter-canonicalizer`` for label → concept-ID resolution
- ``regnskapsnoter-wadm`` for fact serialisation
- ``regnskapsnoter-shacl`` for fact-level validation

Usage::

    from regnskapsnoter_pipeline import RegnskapsnoterPipeline

    pipe = RegnskapsnoterPipeline(leaf_type="brreg_template")
    out = pipe.convert("path/or/gs://uri/to.pdf", period_end="2024-12-31")
    print(f"facts: {out.enrichment.n_facts_emitted}")
    print(f"validation conforms: {out.enrichment.validation.conforms}")
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter, PdfFormatOption

from .configs import get_config
from .enrichment import EnrichmentResult, enrich


@dataclass
class PipelineOutput:
    document: object  # DoclingDocument
    enrichment: EnrichmentResult
    leaf_type: str
    pdf_uri: str


class RegnskapsnoterPipeline:
    """End-to-end pipeline runner.

    Wraps ``DocumentConverter`` + the enrichment chain. Stateless w.r.t. the
    converter (it is reusable across PDFs) so callers pay the heavy
    initialisation cost (loading OCR models) only once per process.
    """

    def __init__(
        self,
        *,
        leaf_type: str = "brreg_template",
        audit_ledger_path: Optional[str] = None,
        use_fuzzy: bool = True,
        use_embedding: bool = False,
    ) -> None:
        self.leaf_type = leaf_type
        self.use_fuzzy = use_fuzzy
        self.use_embedding = use_embedding
        self._opts = get_config(leaf_type, audit_ledger_path=audit_ledger_path)
        self._converter = DocumentConverter(format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=self._opts),
        })

    @property
    def cascade_voters_total(self) -> int:
        return sum(1 for v in self._opts.ocr_options.voters if v.enabled)

    def convert(
        self,
        pdf_uri: str,
        *,
        period_end: Optional[str] = None,
    ) -> PipelineOutput:
        """Convert a PDF and emit WADM-annotated, SHACL-validated facts."""
        conv = self._converter.convert(pdf_uri)
        doc = conv.document
        enrichment = enrich(
            doc,
            pdf_uri=pdf_uri,
            period_end=period_end,
            use_fuzzy=self.use_fuzzy,
            use_embedding=self.use_embedding,
            cascade_voters_total=self.cascade_voters_total,
        )
        return PipelineOutput(
            document=doc,
            enrichment=enrichment,
            leaf_type=self.leaf_type,
            pdf_uri=pdf_uri,
        )
