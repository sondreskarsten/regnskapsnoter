"""Tests for regnskapsnoter-pipeline.

Configuration tests are pure-Python; enrichment tests use a hand-rolled
synthetic DoclingDocument-shaped object so they don't need a live OCR
pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from regnskapsnoter_pipeline.configs import (
    REGISTRY,
    brreg_template,
    konsernregnskap,
    auditor_report,
    tx_log,
    get_config,
)
from regnskapsnoter_pipeline.enrichment import enrich


def test_registry_has_4_leaf_types():
    assert set(REGISTRY) == {"brreg_template", "konsernregnskap", "auditor_report", "tx_log"}


def test_brreg_template_is_full_cascade():
    opts = brreg_template()
    voters = [v for v in opts.ocr_options.voters if v.enabled]
    assert len(voters) == 6
    assert opts.ocr_options.kind == "cascade"
    assert opts.ocr_options.column_drop_veto is True
    assert opts.ocr_options.force_full_page_ocr is True


def test_auditor_report_is_cheap_cascade():
    opts = auditor_report()
    voters = [v for v in opts.ocr_options.voters if v.enabled]
    assert len(voters) == 3
    assert opts.do_table_structure is False  # auditor reports are mostly prose
    assert opts.ocr_options.column_drop_veto is False


def test_tx_log_requires_unanimous_table_cells():
    opts = tx_log()
    assert opts.ocr_options.require_unanimous_for_table_cells is True
    assert opts.ocr_options.column_drop_veto is True


def test_konsernregnskap_uses_full_cascade():
    opts = konsernregnskap()
    voters = [v for v in opts.ocr_options.voters if v.enabled]
    assert len(voters) == 6


def test_get_config_unknown_raises():
    with pytest.raises(ValueError, match="Unknown pipeline config"):
        get_config("not_a_real_leaf_type")


def test_get_config_passes_through_kwargs():
    opts = get_config("brreg_template", audit_ledger_path="/tmp/x.jsonl")
    assert opts.ocr_options.audit_ledger_path == "/tmp/x.jsonl"


# ---- Synthetic Docling document for enrichment ----

@dataclass
class _BBox:
    l: float = 0.0
    t: float = 0.0
    r: float = 100.0
    b: float = 100.0


@dataclass
class _Prov:
    page_no: int = 1
    bbox: _BBox = field(default_factory=_BBox)


@dataclass
class _TextItem:
    text: str
    prov: List[_Prov] = field(default_factory=lambda: [_Prov()])


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
    texts: List[_TextItem] = field(default_factory=list)
    tables: List[_TableData] = field(default_factory=list)


def _make_balance_sheet_doc():
    """A tiny synthetic doc with three rows: parent + 2 children that sum correctly."""
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


def test_enrichment_emits_facts_from_synthetic_table():
    doc = _make_balance_sheet_doc()
    res = enrich(
        doc,
        pdf_uri="gs://b/x.pdf",
        period_end="2024-12-31",
        use_embedding=False,
        cascade_voters_total=7,
    )
    assert res.n_labels_seen >= 3
    assert res.n_labels_resolved >= 3
    assert res.n_facts_emitted == 3
    # All three should pass calc-arc validation: 100 + 200 = 300
    assert res.validation is not None
    assert res.validation.conforms


def test_enrichment_quarantines_bad_calc_arc():
    """Poison the parent value so calc-arc validation fails."""
    cells = [
        _TableCell("Eiendeler", 0, 0),
        _TableCell("500", 0, 1),  # WRONG: should be 300
        _TableCell("Anleggsmidler", 1, 0),
        _TableCell("100", 1, 1),
        _TableCell("Omløpsmidler", 2, 0),
        _TableCell("200", 2, 1),
    ]
    doc = _SyntheticDoc(
        texts=[],
        tables=[_TableData(data=_TableContent(table_cells=cells))],
    )
    res = enrich(
        doc, pdf_uri="gs://b/x.pdf", period_end="2024-12-31",
        use_embedding=False, cascade_voters_total=7,
    )
    assert res.validation is not None
    assert not res.validation.conforms
    assert len(res.validation.failing) == 1


def test_enrichment_skips_unresolvable_labels():
    cells = [
        _TableCell("Some random nonsense xyzzy", 0, 0),
        _TableCell("123", 0, 1),
    ]
    doc = _SyntheticDoc(
        texts=[],
        tables=[_TableData(data=_TableContent(table_cells=cells))],
    )
    res = enrich(
        doc, pdf_uri="gs://b/x.pdf", period_end="2024-12-31",
        use_fuzzy=False, use_embedding=False,
        cascade_voters_total=7,
    )
    assert res.n_facts_emitted == 0
