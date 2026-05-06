"""Per-document cascade summary roll-up.

Audit C9 flagged that per-cell metadata was set but a per-document roll-up
("how many cells unanimous? how many reliable? how many quarantined?")
was never produced.

The summary aggregates across all pages of one ConversionResult so a
downstream consumer can read a single ``CascadeSummary`` object instead
of having to walk every page's diagnostics.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class CascadeSummary:
    """Per-document cascade roll-up.

    Populated incrementally by :class:`CascadeOcrModel` as it processes
    pages. Read by callers via :meth:`CascadeOcrModel.summary`.
    """

    n_pages: int = 0

    # Bbox-cluster vote diagnostics
    n_clusters_total: int = 0
    n_clusters_committed: int = 0
    n_clusters_unanimous: int = 0
    n_clusters_minority: int = 0      # below threshold; not committed

    # Token-level vote diagnostics
    n_tokens_committed: int = 0
    n_tokens_unanimous: int = 0

    # Voter health
    voters_attempted: List[str] = field(default_factory=list)
    voters_column_dropped_pages: Dict[str, int] = field(default_factory=dict)
    n_voters: int = 0

    def update_from_bbox(self, diagnostics: dict, threshold: int) -> None:
        """Fold one page's bbox-vote diagnostics into the summary."""
        page_dropped: List[str] = []
        for key, d in diagnostics.items():
            if not key.startswith("cluster:"):
                continue
            self.n_clusters_total += 1
            if d.get("n_voters_hit", 0) >= threshold:
                self.n_clusters_committed += 1
            else:
                self.n_clusters_minority += 1
            if d.get("n_voters_hit", 0) == d.get("n_voters_attempted", -1):
                self.n_clusters_unanimous += 1
            for v in d.get("column_dropped_voters", []) or []:
                if v not in page_dropped:
                    page_dropped.append(v)
        for v in page_dropped:
            self.voters_column_dropped_pages[v] = (
                self.voters_column_dropped_pages.get(v, 0) + 1
            )

    def update_from_token(self, diagnostics: dict) -> None:
        for key, d in diagnostics.items():
            if not key.startswith("token:"):
                continue
            self.n_tokens_committed += 1
            if d.get("unanimous"):
                self.n_tokens_unanimous += 1

    @property
    def fraction_clusters_unanimous(self) -> float:
        if self.n_clusters_total == 0:
            return 0.0
        return self.n_clusters_unanimous / self.n_clusters_total

    @property
    def fraction_clusters_committed(self) -> float:
        if self.n_clusters_total == 0:
            return 0.0
        return self.n_clusters_committed / self.n_clusters_total

    def to_dict(self) -> dict:
        """Serialise to a dict suitable for JSON or DoclingDocument metadata."""
        return {
            "n_pages": self.n_pages,
            "n_voters": self.n_voters,
            "voters_attempted": list(self.voters_attempted),
            "voters_column_dropped_pages": dict(self.voters_column_dropped_pages),
            "n_clusters_total": self.n_clusters_total,
            "n_clusters_committed": self.n_clusters_committed,
            "n_clusters_unanimous": self.n_clusters_unanimous,
            "n_clusters_minority": self.n_clusters_minority,
            "fraction_clusters_unanimous": round(self.fraction_clusters_unanimous, 4),
            "fraction_clusters_committed": round(self.fraction_clusters_committed, 4),
            "n_tokens_committed": self.n_tokens_committed,
            "n_tokens_unanimous": self.n_tokens_unanimous,
        }
