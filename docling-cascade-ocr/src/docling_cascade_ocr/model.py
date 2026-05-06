"""CascadeOcrModel — Docling ``BaseOcrModel`` subclass that runs N OCR voters
and produces consensus ``TextCell``s.

This is the integration point with Docling's OCR factory. The factory (registered
via setuptools entry-point ``docling`` group, function ``ocr_engines``) maps
``CascadeOcrOptions`` to this class.

Wrap-don't-replace: the cascade does not replace Docling's existing OCR engines.
Each voter is independent. Docling's default engine can also be wired in as one
voter (``docling_default``) by a small adapter, giving us up to 8 voters
including pix2struct.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import List, Optional, Type

from docling_core.types.doc.page import TextCell

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.models.base_ocr_model import BaseOcrModel
from docling.utils.profiling import TimeRecorder

from .ledger import AuditLedger
from .options import CascadeOcrOptions
from .vote import xalign_vote
from .voters import build_voters

_log = logging.getLogger(__name__)


class CascadeOcrModel(BaseOcrModel):
    """Multi-DGP OCR voter cascade.

    Behavior:
    1. Determine OCR rectangles via the inherited ``get_ocr_rects``.
    2. Render the page at the configured scale.
    3. Run all enabled voters in parallel against each rectangle.
    4. Run ``xalign_vote`` to produce consensus cells, with column-drop veto.
    5. Optionally write to an audit ledger.
    6. Hand consensus cells to ``post_process_cells`` so they enter Docling's
       normal pipeline (layout, table-structure, document assembly).
    """

    def __init__(
        self,
        *,
        enabled: bool,
        artifacts_path: Optional[Path],
        options: CascadeOcrOptions,
        accelerator_options: AcceleratorOptions,
    ) -> None:
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: CascadeOcrOptions = options
        self.scale = 3  # 72 DPI base * 3 ≈ 216 DPI; matches EasyOCR default
        self._voters = []
        self._ledger = AuditLedger(options.audit_ledger_path)

        if not enabled:
            return

        from docling.datamodel.accelerator_options import AcceleratorDevice
        from docling.utils.accelerator_utils import decide_device
        device = decide_device(accelerator_options.device)
        use_gpu = any(
            device.startswith(x) for x in [AcceleratorDevice.CUDA.value, AcceleratorDevice.MPS.value]
        )

        self._voters = build_voters(options.voters, lang=options.lang, use_gpu=use_gpu)
        if not self._voters:
            _log.warning(
                "Cascade OCR enabled but no voters available. Install at least one engine "
                "extra (e.g. `pip install docling-cascade-ocr[tesseract]`)."
            )

    @classmethod
    def get_options_type(cls) -> Type[CascadeOcrOptions]:
        return CascadeOcrOptions

    def __call__(
        self, conv_res: ConversionResult, page_batch: Iterable[Page]
    ) -> Iterable[Page]:
        if not self.enabled or not self._voters:
            yield from page_batch
            return

        for page in page_batch:
            assert page._backend is not None
            if not page._backend.is_valid():
                yield page
                continue

            with TimeRecorder(conv_res, "ocr-cascade"):
                ocr_rects = self.get_ocr_rects(page)
                if not ocr_rects:
                    yield page
                    continue

                # Render the page once at the chosen scale; each voter receives the
                # same image so their observations are commensurable.
                page_image = page._backend.get_page_image(scale=self.scale)
                # Normalise: voter coordinate system is page-coordinate (pre-scale)
                scaled_rects = self._scale_rects(ocr_rects, scale=self.scale)

                per_voter = self._run_voters(page_image, scaled_rects)

                # Re-scale voter outputs back to page coordinates
                per_voter = {
                    name: [self._scale_cell_back(c, self.scale) for c in cells]
                    for name, cells in per_voter.items()
                }

                consensus, diagnostics = self._vote(per_voter, page)

                self._ledger.write_page(
                    document_id=str(conv_res.input.file),
                    page_no=page.page_no,
                    per_voter_cells=per_voter,
                    consensus_cells=consensus,
                    diagnostics=diagnostics,
                    page_size=(page.size.width, page.size.height) if page.size else None,
                    column_dropped_voters=(
                        next(iter(diagnostics.values()), {}).get("column_dropped_voters", [])
                        if diagnostics else []
                    ),
                )

                self.post_process_cells(consensus, page)

            yield page

    def _vote(self, per_voter, page):
        """Dispatch the configured vote mode(s) and merge consensus.

        Returns ``(consensus_cells, diagnostics)``. The diagnostics dict is
        mode-tagged: bbox-vote diagnostics under ``"cluster:i"`` keys, token
        diagnostics under ``"token:i"`` keys.
        """
        from .token_vote import token_vote, consensus_to_textcells

        mode = self.options.vote_mode
        consensus_cells = []
        diagnostics = {}

        if mode in ("bbox", "both"):
            bbox_consensus, bbox_diag = xalign_vote(
                per_voter,
                page_size=(page.size.width, page.size.height) if page.size else None,
                min_voters_for_commit=self.options.min_voters_for_commit,
                column_drop_veto=self.options.column_drop_veto,
            )
            consensus_cells.extend(bbox_consensus)
            diagnostics.update(bbox_diag)

        if mode in ("token", "both"):
            tv = token_vote(
                per_voter,
                min_voters_for_commit=self.options.min_voters_for_commit,
            )
            token_cells = consensus_to_textcells(tv)
            # Re-index continuing from existing consensus_cells
            offset = len(consensus_cells)
            for i, c in enumerate(token_cells):
                consensus_cells.append(c.model_copy(update={"index": offset + i}))
            for i, nc in enumerate(tv.numeric):
                diagnostics[f"token:{i}"] = nc.to_dict()

        return consensus_cells, diagnostics

    # ---- helpers ----

    def _run_voters(self, page_image, ocr_rects):
        """Run all voters in parallel, with per-voter timeout."""
        per_voter = {}
        with ThreadPoolExecutor(max_workers=max(1, len(self._voters))) as ex:
            futures = {ex.submit(v.run, page_image, ocr_rects): v for v in self._voters}
            for fut, voter in list(futures.items()):
                spec = next(s for s in self.options.voters if s.name == voter.name)
                try:
                    cells = fut.result(timeout=spec.timeout_s)
                    per_voter[voter.name] = cells
                except FuturesTimeout:
                    _log.warning("Voter %s timed out (%.1fs)", voter.name, spec.timeout_s)
                    per_voter[voter.name] = []
                except Exception as e:
                    _log.warning("Voter %s failed: %s", voter.name, e)
                    per_voter[voter.name] = []
        return per_voter

    @staticmethod
    def _scale_rects(rects, *, scale):
        """Scale OCR rectangles from page units → image pixels."""
        from docling_core.types.doc import BoundingBox, CoordOrigin
        return [
            BoundingBox(
                l=r.l * scale, t=r.t * scale,
                r=r.r * scale, b=r.b * scale,
                coord_origin=CoordOrigin.TOPLEFT,
            )
            for r in rects
        ]

    @staticmethod
    def _scale_cell_back(cell: TextCell, scale: int) -> TextCell:
        from docling_core.types.doc import BoundingBox, CoordOrigin
        from docling_core.types.doc.page import BoundingRectangle
        bb = cell.rect.to_bounding_box()
        return TextCell(
            index=cell.index,
            text=cell.text,
            orig=cell.orig,
            from_ocr=True,
            confidence=cell.confidence,
            rect=BoundingRectangle.from_bounding_box(BoundingBox(
                l=bb.l / scale, t=bb.t / scale,
                r=bb.r / scale, b=bb.b / scale,
                coord_origin=CoordOrigin.TOPLEFT,
            )),
        )
