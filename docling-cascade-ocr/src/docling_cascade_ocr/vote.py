"""Cascade voting algorithm.

Inputs are per-voter ``list[TextCell]`` for a single page. Output is a single
consensus ``list[TextCell]`` plus per-cell vote diagnostics.

Algorithm (the ``ocr-cascade-eval`` v2 verdict):

1. **Cluster cells across voters by bbox overlap.** Two cells from different voters
   refer to the same underlying page region when their bounding boxes overlap by IoU
   ≥ ``iou_threshold``. Cluster size is bounded by the number of voters.

2. **Within each cluster, vote on text.** Texts are normalised (NFKC fold,
   collapse whitespace, normalise hyphens/minus, strip parenthesised-negative
   convention to a leading minus) before comparison. The most-voted-for text wins.

3. **Apply column-drop veto.** ``xalign_vote`` projects per-voter words onto the
   page x-axis to detect column structure. Any voter whose tokens collapse two
   semantically distinct columns into one is marked ``column_dropped`` for the
   PAGE and excluded from voting on every cluster on that page.

4. **Commit the consensus cell** when ``hits >= min_voters_for_commit``. Otherwise
   the cluster is retained in the diagnostics but the consensus cell is left out
   of the page's textline cells.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell


# -- Text normalisation --

_HYPHEN_LIKE = "\u2010\u2011\u2012\u2013\u2014\u2212"  # hyphen, non-breaking hyphen, figure dash, en dash, em dash, minus
_HYPHEN_TO = "-"
_PAREN_NEG = re.compile(r"^\(\s*([\d\s.,]+)\s*\)$")


def normalise_text(s: str) -> str:
    """Normalise OCR text for comparison.

    - NFKC normalisation
    - Strip / collapse whitespace
    - Hyphen-like characters → ASCII hyphen
    - Parenthesised numbers → leading minus
    - Norwegian thousands separator (space) preserved as-is for now
    """
    s = unicodedata.normalize("NFKC", s)
    s = "".join(_HYPHEN_TO if c in _HYPHEN_LIKE else c for c in s)
    s = re.sub(r"\s+", " ", s).strip()
    m = _PAREN_NEG.match(s)
    if m:
        s = "-" + m.group(1)
    return s


# -- Bounding-box helpers --

def bbox_iou(a: BoundingBox, b: BoundingBox) -> float:
    inter_l = max(a.l, b.l)
    inter_t = max(a.t, b.t)
    inter_r = min(a.r, b.r)
    inter_b = min(a.b, b.b)
    if inter_r <= inter_l or inter_b <= inter_t:
        return 0.0
    inter = (inter_r - inter_l) * (inter_b - inter_t)
    a_area = max(1.0, (a.r - a.l) * (a.b - a.t))
    b_area = max(1.0, (b.r - b.l) * (b.b - b.t))
    return inter / (a_area + b_area - inter)


def merge_bbox(bboxes: List[BoundingBox]) -> BoundingBox:
    return BoundingBox(
        l=min(b.l for b in bboxes),
        t=min(b.t for b in bboxes),
        r=max(b.r for b in bboxes),
        b=max(b.b for b in bboxes),
        coord_origin=CoordOrigin.TOPLEFT,
    )


# -- xalign column-drop veto --

def detect_column_drop(
    per_voter_cells: Dict[str, List[TextCell]],
    page_width: float,
    *,
    min_columns_for_check: int = 2,
    drop_threshold_x_diff: float = 0.15,
) -> List[str]:
    """Detect voters that have dropped a column on this page.

    Heuristic from ocr-cascade-eval: build per-voter column histograms by binning
    token x-centroids; the modal voter's bin count = expected column count. A
    voter is flagged as column-dropped when EITHER:
      - its bin count is below the mode AND its largest x-gap exceeds
        ``drop_threshold_x_diff * page_width`` (typical collapsed-rows case), OR
      - its bin count is materially below the mode (e.g. only 1 cluster vs 2+)
        AND its total cell count is also materially below the mode count
        (typical sparse-merger case).

    For pages with fewer than ``min_columns_for_check`` columns this is a no-op.
    """
    if not per_voter_cells:
        return []

    bin_count: Dict[str, int] = {}
    max_gap: Dict[str, float] = {}
    cell_count: Dict[str, int] = {}
    for v, cells in per_voter_cells.items():
        cell_count[v] = len(cells)
        if not cells:
            bin_count[v] = 0
            max_gap[v] = 0.0
            continue
        xs = sorted(((c.rect.r_x0 + c.rect.r_x2) / 2.0) for c in cells)
        gaps = [xs[i+1] - xs[i] for i in range(len(xs) - 1)] or [0.0]
        max_gap[v] = max(gaps)
        n_bins = 1
        for g in gaps:
            if g > 0.05 * page_width:
                n_bins += 1
        bin_count[v] = n_bins

    mode_bins = Counter(bin_count.values()).most_common(1)[0][0]
    if mode_bins < min_columns_for_check:
        return []

    # Among voters at the mode, the typical cell count
    cells_at_mode = [cell_count[v] for v in bin_count if bin_count[v] == mode_bins]
    mode_cells = max(cells_at_mode) if cells_at_mode else 0

    dropped: List[str] = []
    for v, nbins in bin_count.items():
        if nbins >= mode_bins:
            continue
        # Case 1: voter sees fewer columns AND has a wide x-gap → typical collapse
        if max_gap[v] > drop_threshold_x_diff * page_width:
            dropped.append(v)
            continue
        # Case 2: voter sees fewer columns AND has materially fewer cells → typical merger
        if cell_count[v] < mode_cells * 0.7:
            dropped.append(v)
    return dropped


# -- Clustering and voting --

def cluster_cells_across_voters(
    per_voter_cells: Dict[str, List[TextCell]],
    *,
    iou_threshold: float = 0.3,
) -> List[Dict[str, TextCell]]:
    """Cluster cells from different voters by bbox overlap.

    Returns a list of clusters; each cluster is a dict ``{voter_name: TextCell}``
    containing at most one cell per voter.
    """
    clusters: List[Dict[str, TextCell]] = []
    for voter, cells in per_voter_cells.items():
        for c in cells:
            cb = c.rect.to_bounding_box()
            placed = False
            for cluster in clusters:
                # Compare against any cell already in cluster
                for _, existing in cluster.items():
                    if bbox_iou(cb, existing.rect.to_bounding_box()) >= iou_threshold:
                        if voter not in cluster:
                            cluster[voter] = c
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                clusters.append({voter: c})
    return clusters


def vote_cluster(cluster: Dict[str, TextCell]) -> Tuple[str, int, List[Tuple[str, List[str]]]]:
    """Vote on the consensus text for a single cluster.

    Returns (consensus_text, n_voters_for_consensus, alternatives).
    Alternatives is a list of ``(text, voters_that_said_it)`` for non-winning options.
    """
    norm_to_voters: Dict[str, List[str]] = defaultdict(list)
    for voter, cell in cluster.items():
        nt = normalise_text(cell.text)
        norm_to_voters[nt].append(voter)
    # Pick winner: most voters; tiebreak by alphabetical to be deterministic
    ranked = sorted(norm_to_voters.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    consensus = ranked[0][0]
    n_winners = len(ranked[0][1])
    alts = [(t, vs) for t, vs in ranked[1:]]
    return consensus, n_winners, alts


def xalign_vote(
    per_voter_cells: Dict[str, List[TextCell]],
    *,
    page_size: Optional[Tuple[float, float]] = None,
    min_voters_for_commit: int = 7,
    iou_threshold: float = 0.3,
    column_drop_veto: bool = True,
) -> Tuple[List[TextCell], Dict[str, dict]]:
    """Run the cascade vote.

    Returns ``(consensus_cells, diagnostics_per_cluster)``.

    ``diagnostics_per_cluster`` is keyed by ``f"cluster:{i}"`` with values
    ``{voters_hit, voters_attempted, alternatives, x0, y0, x1, y1, ...}``.
    """
    page_width = page_size[0] if page_size else 1000.0

    dropped_voters: List[str] = []
    if column_drop_veto:
        dropped_voters = detect_column_drop(per_voter_cells, page_width)

    active = {v: cells for v, cells in per_voter_cells.items() if v not in dropped_voters}
    clusters = cluster_cells_across_voters(active, iou_threshold=iou_threshold)

    consensus_cells: List[TextCell] = []
    diagnostics: Dict[str, dict] = {}
    for i, cluster in enumerate(clusters):
        text, n, alts = vote_cluster(cluster)
        attempted = list(cluster.keys())
        winners = [v for v, c in cluster.items() if normalise_text(c.text) == text]

        # Build the merged bbox from winning voters only
        winner_bboxes = [cluster[v].rect.to_bounding_box() for v in winners]
        bb = merge_bbox(winner_bboxes)

        diagnostics[f"cluster:{i}"] = {
            "consensus_text": text,
            "voters_hit": winners,
            "voters_attempted": attempted,
            "n_voters_hit": n,
            "n_voters_attempted": len(attempted),
            "alternatives": [{"text": t, "voters": vs} for t, vs in alts],
            "bbox": [bb.l, bb.t, bb.r, bb.b],
            "column_dropped_voters": dropped_voters,
        }

        if n >= min_voters_for_commit:
            consensus_cells.append(TextCell(
                index=len(consensus_cells),
                text=text,
                orig=text,
                from_ocr=True,
                confidence=n / max(1, len(attempted)),
                rect=BoundingRectangle.from_bounding_box(bb),
            ))

    return consensus_cells, diagnostics
