"""Audit ledger writer.

Stores per-page voter outputs and consensus diagnostics as JSON Lines so the
cascade decision is fully reproducible from the ledger alone (the multi-DGP
pattern: store every observation, not just the consensus).

Schema mirrors ``ocr-cascade-eval/audit/cascade/v2_10signals/voting.json`` so a
single downstream auditor can read both legacy and new outputs.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional


class AuditLedger:
    def __init__(self, path: Optional[str]):
        self.path = path
        self._enabled = path is not None
        if self._enabled:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def write_page(
        self,
        *,
        document_id: str,
        page_no: int,
        per_voter_cells: Dict[str, List],  # voter_name -> list[TextCell]
        consensus_cells: List,
        diagnostics: Dict[str, dict],
        page_size: Optional[tuple] = None,
        column_dropped_voters: Optional[List[str]] = None,
    ) -> None:
        if not self._enabled:
            return
        record = {
            "_meta": {
                "audit_schema_version": "v2",
                "ts": time.time(),
                "document_id": document_id,
                "page_no": page_no,
                "page_size": list(page_size) if page_size else None,
                "voters": list(per_voter_cells.keys()),
                "column_dropped_voters": column_dropped_voters or [],
            },
            "per_voter": {
                v: [self._cell_to_json(c) for c in cells]
                for v, cells in per_voter_cells.items()
            },
            "consensus": [self._cell_to_json(c) for c in consensus_cells],
            "diagnostics": diagnostics,
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")

    @staticmethod
    def _cell_to_json(cell) -> dict:
        bb = cell.rect.to_bounding_box()
        return {
            "text": cell.text,
            "confidence": cell.confidence,
            "bbox": [bb.l, bb.t, bb.r, bb.b],
            "from_ocr": cell.from_ocr,
        }
