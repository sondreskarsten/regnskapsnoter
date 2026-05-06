"""regnskapsnoter-eval — v2-fixture eval harness.

Reproduces the scoring methodology from
``ocr-cascade-eval/audit/build_v2_audit.py`` so the central empirical claim
("99/100 reliable on the v2 fixture") is verifiable from this repo's CI.

Scoring contract:

- Truth source: BRREG live API ``/regnskapsregisteret/regnskap/{orgnr}`` ->
  ``key_metrics`` integers, snapshotted to GCS in
  ``raw/ocr_eval_v2_10pdfs_300dpi/audit/brreg_ground_truth/{orgnr}.json``.
- A truth value is "recovered" by a voter (or by the consensus) iff
  :func:`number_present` finds it in the voter's output text.
- Reliability = fraction of (orgnr, label) pairs where ``≥ min_voters``
  voters recovered the truth value.
"""
from __future__ import annotations

from .scoring import (
    EngineScore,
    FixtureScore,
    ReliabilityReport,
    number_present,
    score_consensus,
    score_engine_text,
    score_fixture,
    score_per_voter,
)
from .truth import (
    BrregGroundTruth,
    load_truth_from_gcs,
    load_truth_from_local,
    truth_numbers,
)

__version__ = "0.1.0"

__all__ = [
    "BrregGroundTruth",
    "EngineScore",
    "FixtureScore",
    "ReliabilityReport",
    "load_truth_from_gcs",
    "load_truth_from_local",
    "number_present",
    "score_consensus",
    "score_engine_text",
    "score_fixture",
    "score_per_voter",
    "truth_numbers",
]
