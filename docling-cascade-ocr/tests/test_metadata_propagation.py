"""Cascade metadata propagation contract (audit C12).

The audit said: "Table cells inherit cascade metadata via Docling's
existing cell-to-table-cell mapping with do_cell_matching=True. Asserted
but not verified. TableFormer might not propagate the cell.metadata dict."

When this test was written, the verification revealed:

  - ``TextCell`` (the cascade's output cell type) has NO ``metadata`` field.
    The Docling schema only carries ``confidence``, ``from_ocr``, ``text``,
    ``orig``, ``rect``, ``index``, ``rgba``, ``text_direction``.

  - ``TableCell`` (TableFormer's output cell type) has NO ``confidence``
    field. It carries text + grid coordinates only.

  - Therefore the audit's proposed propagation path ("cell.metadata dict")
    cannot be tested because the field doesn't exist. The cascade's
    per-cell metadata is observable only on ``parsed_page.textline_cells``,
    not on ``table.data.table_cells``.

This file pins down those facts as a contract test. If a future Docling
version adds a metadata dict, this test will detect the change and we
can wire propagation properly. If TableFormer starts dropping
``confidence`` from textline cells too, this test will catch that as well.
"""
from __future__ import annotations

import pytest

from docling_core.types.doc.page import TextCell


# ---- Schema contract ----

def test_textcell_schema_has_no_metadata_field():
    """If this changes, the cascade can start writing per-cell metadata."""
    fields = list(TextCell.model_fields)
    assert "metadata" not in fields, (
        "TextCell schema gained a 'metadata' field. The cascade should "
        "now propagate cluster-level diagnostics (n_voters_hit, unanimous, "
        "column_dropped_voters) per cell. Update CascadeOcrModel._vote to "
        "set this field on consensus cells."
    )


def test_textcell_schema_has_confidence_and_from_ocr():
    """The cascade depends on these two fields. If either is removed, the
    confidence-carrying contract breaks."""
    fields = list(TextCell.model_fields)
    assert "confidence" in fields
    assert "from_ocr" in fields


def test_tablecell_schema_has_no_confidence_field():
    """TableFormer's TableCell drops per-cell confidence by design.

    Downstream consumers that need per-numeric reliability cannot read it
    from ``table.data.table_cells`` — they must consume the cascade audit
    ledger or the parsed_page.textline_cells list directly.
    """
    from docling_core.types.doc.document import TableCell
    fields = list(TableCell.model_fields)
    assert "confidence" not in fields, (
        "TableCell schema gained a 'confidence' field. The cascade can now "
        "populate per-table-cell reliability — wire it through TableFormer."
    )


# ---- Cascade output preserves confidence + from_ocr ----

class TestCascadeCellPreservation:
    """The cascade emits TextCells with confidence in [0,1] and from_ocr=True.
    These ARE preserved through the post_process_cells handoff to Docling
    (write to parsed_page.textline_cells); they are NOT preserved through
    TableFormer's separate cell-extraction path."""

    def test_consensus_cells_have_confidence_in_unit_interval(self):
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_core.types.doc.page import BoundingRectangle
        from docling_cascade_ocr.token_vote import (
            consensus_to_textcells,
            token_vote,
        )

        # Build two voters that both see the same value
        cell = TextCell(
            index=0, text="12 345", orig="12 345", from_ocr=True,
            confidence=0.9,
            rect=BoundingRectangle.from_bounding_box(BoundingBox(
                l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT,
            )),
        )
        per_voter = {f"v{i}": [cell] for i in range(7)}
        result = token_vote(per_voter, min_voters_for_commit=7)
        cells = consensus_to_textcells(result)
        assert cells, "no consensus cells produced"
        for c in cells:
            assert 0.0 <= c.confidence <= 1.0
            assert c.from_ocr is True

    def test_consensus_cell_confidence_reflects_vote_share(self):
        """When 7 of 8 voters agree, confidence must be 7/8."""
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_core.types.doc.page import BoundingRectangle
        from docling_cascade_ocr.token_vote import (
            consensus_to_textcells,
            token_vote,
        )

        good = TextCell(
            index=0, text="12 345", orig="12 345", from_ocr=True,
            confidence=0.9,
            rect=BoundingRectangle.from_bounding_box(BoundingBox(
                l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT,
            )),
        )
        bad = TextCell(
            index=0, text="nothing here", orig="nothing", from_ocr=True,
            confidence=0.9,
            rect=BoundingRectangle.from_bounding_box(BoundingBox(
                l=0, t=0, r=10, b=10, coord_origin=CoordOrigin.TOPLEFT,
            )),
        )
        per_voter = {f"v{i}": [good] for i in range(7)}
        per_voter["bad"] = [bad]
        result = token_vote(per_voter, min_voters_for_commit=7)
        cells = consensus_to_textcells(result)
        assert cells
        # 7 of 8 voters hit -> confidence = 7/8 = 0.875
        assert cells[0].confidence == pytest.approx(7 / 8)


# ---- Documented limitation: where to read cascade reliability from ----

def test_cascade_audit_ledger_is_canonical_source_of_per_value_reliability():
    """The contract: consumers wanting per-value reliability MUST read it
    from the cascade audit ledger (CascadeOcrModel.options.audit_ledger_path)
    or from CascadeOcrModel.summary, NOT from DoclingDocument.tables.

    This test asserts that the audit ledger schema carries the diagnostics
    that aren't represented in DoclingDocument's table schema.
    """
    from docling_cascade_ocr.ledger import AuditLedger
    import inspect
    src = inspect.getsource(AuditLedger.write_page)
    # The ledger writes per_voter_cells and diagnostics — the only place
    # these are recorded.
    assert "per_voter_cells" in src
    assert "diagnostics" in src
