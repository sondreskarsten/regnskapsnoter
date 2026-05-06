"""Writeback tests for the enrichment pipeline (audit C8).

Audit C8 flagged: "Resolved facts written back into the DoclingDocument
so downstream consumers reading DoclingDocument see facts there. Reality:
the enrichment returns a *separate* annotations list. The DoclingDocument
is unchanged."

The enrichment now accepts ``writeback_to_document=True`` which appends a
``KeyValueItem`` to ``document.key_value_items`` containing one
key/value GraphCell pair per resolved fact.

These tests verify:

1. Default behaviour (writeback_to_document=False) leaves the document's
   key_value_items untouched.
2. With writeback enabled, key_value_items grows by exactly one
   KeyValueItem per call.
3. The KeyValueItem's GraphData has the right number of cells (2 per fact:
   key + value) and the right number of links (1 per fact).
4. Writeback is idempotent in the sense that calling enrich a second time
   appends a second KeyValueItem (it doesn't mutate the existing one).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pytest

from regnskapsnoter_pipeline import enrich


# Reuse the synthetic table fixture from test_pipeline.py
@dataclass
class _Prov:
    page_no: int = 1
    bbox: object = None
    def __post_init__(self):
        if self.bbox is None:
            self.bbox = type("B", (), {"l": 0.0, "t": 0.0, "r": 100.0, "b": 100.0})()


@dataclass
class _TableCell:
    text: str
    start_row_offset_idx: int
    start_col_offset_idx: int


@dataclass
class _TableContent:
    table_cells: List[_TableCell]


@dataclass
class _TableData:
    data: _TableContent
    prov: List[_Prov] = field(default_factory=lambda: [_Prov()])


@dataclass
class _SyntheticDoc:
    texts: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    key_value_items: list = field(default_factory=list)


def _make_balance_sheet_doc():
    cells = [
        _TableCell("Eiendeler", 0, 0),
        _TableCell("300", 0, 1),
        _TableCell("Anleggsmidler", 1, 0),
        _TableCell("100", 1, 1),
        _TableCell("Omløpsmidler", 2, 0),
        _TableCell("200", 2, 1),
    ]
    return _SyntheticDoc(
        texts=[],
        tables=[_TableData(data=_TableContent(table_cells=cells))],
    )


# ---- Tests ----

def test_writeback_disabled_leaves_document_untouched():
    doc = _make_balance_sheet_doc()
    res = enrich(
        doc, pdf_uri="gs://b/x.pdf", period_end="2024-12-31",
        use_embedding=False, validate=False,
        writeback_to_document=False,
    )
    assert res.n_facts_emitted >= 1
    # key_value_items must remain empty
    assert doc.key_value_items == []


def test_writeback_appends_one_key_value_item():
    doc = _make_balance_sheet_doc()
    res = enrich(
        doc, pdf_uri="gs://b/x.pdf", period_end="2024-12-31",
        use_embedding=False, validate=False,
        writeback_to_document=True,
    )
    assert res.n_facts_emitted >= 1
    # Exactly one KeyValueItem appended for this enrich() call
    assert len(doc.key_value_items) == 1


def test_writeback_graph_has_one_cell_pair_per_fact():
    doc = _make_balance_sheet_doc()
    res = enrich(
        doc, pdf_uri="gs://b/x.pdf", period_end="2024-12-31",
        use_embedding=False, validate=False,
        writeback_to_document=True,
    )
    n_facts = res.n_facts_emitted
    kvi = doc.key_value_items[0]
    # 2 cells per fact (key + value)
    assert len(kvi.graph.cells) == 2 * n_facts
    # 1 link per fact (key -> value)
    assert len(kvi.graph.links) == n_facts


def test_writeback_cell_text_contains_concept_id():
    doc = _make_balance_sheet_doc()
    res = enrich(
        doc, pdf_uri="gs://b/x.pdf", period_end="2024-12-31",
        use_embedding=False, validate=False,
        writeback_to_document=True,
    )
    kvi = doc.key_value_items[0]
    # At least one KEY cell carries 'regnskap-no:'
    from docling_core.types.doc.labels import GraphCellLabel
    key_texts = [c.text for c in kvi.graph.cells
                 if c.label == GraphCellLabel.KEY]
    assert any("regnskap-no:" in t for t in key_texts), (
        f"no KEY cell carries a regnskap-no concept id; cells: {key_texts}"
    )


def test_writeback_idempotent_on_second_call():
    """Calling enrich twice with writeback appends a second KeyValueItem."""
    doc = _make_balance_sheet_doc()
    enrich(doc, pdf_uri="gs://b/x.pdf", use_embedding=False,
           validate=False, writeback_to_document=True)
    enrich(doc, pdf_uri="gs://b/x.pdf", use_embedding=False,
           validate=False, writeback_to_document=True)
    # Two KeyValueItems = two enrich calls. The pipeline doesn't dedupe
    # — that's a downstream concern.
    assert len(doc.key_value_items) == 2


def test_writeback_no_facts_no_kvi_appended():
    """If no facts resolve, no KeyValueItem is appended."""
    # All-numeric doc → no labels → no facts
    cells = [
        _TableCell("12345", 0, 0),
        _TableCell("67890", 0, 1),
    ]
    doc = _SyntheticDoc(
        texts=[],
        tables=[_TableData(data=_TableContent(table_cells=cells))],
    )
    res = enrich(doc, pdf_uri="gs://b/x.pdf", use_embedding=False,
                 validate=False, writeback_to_document=True)
    assert res.n_facts_emitted == 0
    assert doc.key_value_items == []
