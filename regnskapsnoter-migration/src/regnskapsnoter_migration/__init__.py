"""regnskapsnoter-migration — v1 → v2 shadow-mode runner + drift report.

Audit C11 closed: tools for migrating the 18,924-PDF noter corpus from
the v1 extraction (Gemini PDF prompt) to v2 (cascade + canonicaliser +
SHACL).

Public API:

    from regnskapsnoter_migration import (
        Fact,
        diff_facts,
        DriftReport,
        per_concept_drift,
        per_orgnr_summary,
        write_diff_parquet,
    )

Each function takes plain :class:`Fact` records, so it doesn't bind to
any particular extractor's internal schema. Callers convert their v1 /
v2 outputs to ``Fact`` and feed them in.
"""
from __future__ import annotations

from .diff import (
    DiffEntry,
    DriftReport,
    Fact,
    diff_facts,
    per_concept_drift,
    per_orgnr_summary,
    write_diff_parquet,
)

__version__ = "0.1.0"

__all__ = [
    "DiffEntry",
    "DriftReport",
    "Fact",
    "diff_facts",
    "per_concept_drift",
    "per_orgnr_summary",
    "write_diff_parquet",
]
