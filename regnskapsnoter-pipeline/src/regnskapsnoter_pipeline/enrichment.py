"""Enrichment: walk a converted DoclingDocument and emit WADM annotations.

The enrichment runs AFTER Docling's standard pipeline (cascade OCR → layout →
TableFormer → assembly). Its job is the binding step — turning typed Docling
elements into WADM annotations linked to ``regnskap-no:*`` concept IDs.

Strategy:

1. Iterate over the document's TextItems and TableItems.
2. For each TextItem whose text plausibly looks like a noter heading or
   line-item label, run the canonicalizer.
3. For each TableItem, treat the first row/column as labels and the rest as
   values; resolve labels to concept IDs and emit fact annotations.
4. Run :func:`regnskapsnoter_shacl.validate_facts` over the annotation batch
   and report passing/failing.

This is intentionally conservative: it does NOT attempt to be a full XBRL
extraction. It produces a high-recall, high-precision *first cut* that the
downstream LLM-driven typed extraction (per-note Pydantic schemas from
``regnskap_no.prompts``) can build on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from regnskap_no import api as taxonomy_api
from noter_canonicalizer import resolve as resolve_label
from regnskapsnoter_wadm import Annotation, build_fact_annotation
from regnskapsnoter_shacl import FactValidationReport, validate_facts


_NUMERIC_RE = re.compile(r"^-?\(?[\d\s\u00a0.,]+\)?$")


@dataclass
class EnrichmentResult:
    annotations: List[Annotation] = field(default_factory=list)
    validation: Optional[FactValidationReport] = None
    n_labels_seen: int = 0
    n_labels_resolved: int = 0
    n_facts_emitted: int = 0


def _looks_numeric(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and bool(_NUMERIC_RE.match(s))


def _flatten_table_to_rows(table_data) -> List[List[str]]:
    """Best-effort extraction of a Docling TableData into a list of rows.

    Falls back gracefully if the API surface differs across docling-core
    versions; consumers should treat the rows as a hint, not a contract.
    """
    if hasattr(table_data, "grid"):
        try:
            return [[(cell.text if cell else "") for cell in row] for row in table_data.grid]
        except Exception:
            pass
    if hasattr(table_data, "data") and hasattr(table_data.data, "table_cells"):
        # group cells by row index
        cells = list(table_data.data.table_cells)
        rows: dict = {}
        for c in cells:
            rows.setdefault(c.start_row_offset_idx, []).append(c)
        out = []
        for r in sorted(rows):
            row_cells = sorted(rows[r], key=lambda c: c.start_col_offset_idx)
            out.append([c.text for c in row_cells])
        return out
    return []


def _bbox_of_item(item) -> Tuple[float, float, float, float]:
    """Pull a (l, t, r, b) bbox from a Docling item if it has provenance."""
    try:
        prov = item.prov[0]
        bb = prov.bbox
        return (bb.l, bb.t, bb.r, bb.b)
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def _page_of_item(item) -> int:
    try:
        return int(item.prov[0].page_no)
    except Exception:
        return 1


def _writeback_facts_to_document(document, annotations, *, pdf_uri: str) -> None:
    """Append a single KeyValueItem with one GraphCell per resolved fact.

    Audit C8 — the previous design returned annotations only as a separate
    list. Downstream consumers reading just the DoclingDocument lost the
    enrichment. This writeback puts the resolved facts where any
    DoclingDocument consumer expects key-value extractions: in
    ``document.key_value_items``.

    Each fact becomes one GraphCell whose ``text`` is the concept_id +
    value, and whose ``orig`` carries the original label text. The fact's
    full WADM annotation is preserved separately in
    ``EnrichmentResult.annotations``; this writeback is the lightweight
    in-document mirror.
    """
    if not annotations:
        return
    try:
        from docling_core.types.doc.document import (
            GraphCell, GraphData, GraphLink, KeyValueItem,
        )
        from docling_core.types.doc.labels import GraphCellLabel, GraphLinkLabel
    except ImportError:
        # Older docling-core: silently skip writeback
        return

    cells = []
    for i, ann in enumerate(annotations):
        # WADM annotation body shape:
        #   body[0]: SpecificResource(source='regnskap-no:ConceptId', purpose='classifying')
        #   body[1]: TextualBody(value='1234', purpose='tagging')
        if not ann.body or len(ann.body) < 1:
            continue
        concept_id = getattr(ann.body[0], "source", None)
        if concept_id is None:
            continue
        value_text = ""
        if len(ann.body) >= 2:
            value_text = str(getattr(ann.body[1], "value", "") or "")

        key_cell = GraphCell(
            label=GraphCellLabel.KEY,
            cell_id=2 * i,
            text=str(concept_id),
            orig=str(concept_id),
        )
        val_cell = GraphCell(
            label=GraphCellLabel.VALUE,
            cell_id=2 * i + 1,
            text=value_text,
            orig=value_text,
        )
        cells.append(key_cell)
        cells.append(val_cell)

    if not cells:
        return

    links = [
        GraphLink(
            label=GraphLinkLabel.TO_VALUE,
            source_cell_id=cells[i].cell_id,
            target_cell_id=cells[i + 1].cell_id,
        )
        for i in range(0, len(cells), 2)
    ]

    # KeyValueItem.self_ref must match #/key_value_items/<int>; use the
    # current length as the index so multiple writebacks append cleanly.
    next_index = len(getattr(document, "key_value_items", None) or [])
    kvi = KeyValueItem(
        graph=GraphData(cells=cells, links=links),
        self_ref=f"#/key_value_items/{next_index}",
    )
    if not hasattr(document, "key_value_items") or document.key_value_items is None:
        document.key_value_items = []
    document.key_value_items.append(kvi)


def enrich(
    document,
    *,
    pdf_uri: str,
    period_end: Optional[str] = None,
    use_fuzzy: bool = True,
    use_embedding: bool = False,
    cascade_voters_total: Optional[int] = None,
    creator_id: str = "urn:regnskapsnoter:pipeline:dev",
    validate: bool = True,
    writeback_to_document: bool = False,
) -> EnrichmentResult:
    """Enrich a Docling-converted document.

    Args:
        document: the ``DoclingDocument`` returned by ``ConversionResult.document``.
        pdf_uri: URI of the source PDF (used as WADM ``target.source``).
        period_end: ISO date for ``registrum:periodEnd`` on emitted facts.
        use_fuzzy: whether the canonicalizer's fuzzy stage runs.
        use_embedding: whether the canonicalizer's embedding stage runs.
        cascade_voters_total: total number of voters in the cascade run, for
            populating ``registrum:cascadeConfidence``.
        validate: whether to run the SHACL fact-level validator on the batch.
        writeback_to_document: if True, also append a ``KeyValueItem`` to
            ``document.key_value_items`` containing the resolved facts.
            Audit C8: this lets downstream consumers reading just the
            DoclingDocument see the enrichment without depending on
            ``EnrichmentResult.annotations``.

    Returns:
        ``EnrichmentResult`` with all annotations and a validation report.
    """
    result = EnrichmentResult()

    # ----- text items: try to resolve as noter labels (no value) -----

    texts = getattr(document, "texts", []) or []
    tables = getattr(document, "tables", []) or []

    for item in texts:
        txt = (item.text or "").strip()
        if not txt or _looks_numeric(txt) or len(txt) > 80:
            # Bullet-paragraph long text is not a label; skip
            continue
        result.n_labels_seen += 1
        rr = resolve_label(txt, use_fuzzy=use_fuzzy, use_embedding=use_embedding)
        if not rr.resolved:
            continue
        result.n_labels_resolved += 1
        # We have a label without an obvious value here. Skip — facts emerge
        # from tables. This pass is a sanity check that labels exist in the
        # taxonomy; it does not emit annotations on its own.

    # ----- tables: emit one fact per (label, value) pair -----

    for tbl in tables:
        rows = _flatten_table_to_rows(tbl)
        if not rows:
            continue
        bbox = _bbox_of_item(tbl)
        page_no = _page_of_item(tbl)

        # Heuristic: column 0 is the label, columns 1..N are values per period.
        for row in rows:
            if len(row) < 2:
                continue
            label = (row[0] or "").strip()
            if not label or len(label) > 80:
                continue
            result.n_labels_seen += 1
            rr = resolve_label(label, use_fuzzy=use_fuzzy, use_embedding=use_embedding)
            if not rr.resolved:
                continue
            result.n_labels_resolved += 1

            # Emit one annotation per non-empty numeric value in the row
            for v in row[1:]:
                v = (v or "").strip()
                if not _looks_numeric(v):
                    continue
                ann = build_fact_annotation(
                    pdf_uri=pdf_uri,
                    page_no=page_no,
                    bbox=bbox,
                    concept_id=rr.match.concept_id,
                    value_text=v,
                    consensus_text=label,
                    cascade_voters_total=cascade_voters_total,
                    period_end=period_end,
                    creator_id=creator_id,
                )
                result.annotations.append(ann)
                result.n_facts_emitted += 1

    if validate:
        result.validation = validate_facts(result.annotations)

    if writeback_to_document:
        _writeback_facts_to_document(document, result.annotations, pdf_uri=pdf_uri)

    return result
