"""BRREG ground-truth loader for the v2 fixture.

The truth artifacts live at
``gs://sondre_brreg_data/raw/ocr_eval_v2_10pdfs_300dpi/audit/brreg_ground_truth/{orgnr}.json``.
Each file is a snapshot of the BRREG API response for one orgnr, containing
``key_metrics`` (a flat numeric dict) plus the full nested raw response.

For CI we load from a local mirror (committed under ``tests/data/``) so the
eval harness has no GCS dependency. The GCS loader is available for
production runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set


@dataclass
class BrregGroundTruth:
    orgnr: str
    journalnr: Optional[str] = None
    period_from: Optional[str] = None
    period_to: Optional[str] = None
    regnskapstype: Optional[str] = None
    key_metrics: Dict[str, float] = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "BrregGroundTruth":
        return cls(
            orgnr=str(d["orgnr"]),
            journalnr=d.get("journalnr"),
            period_from=d.get("period_from"),
            period_to=d.get("period_to"),
            regnskapstype=d.get("regnskapstype"),
            key_metrics=d.get("key_metrics") or {},
            raw_response=d.get("raw_response") or {},
        )

    @classmethod
    def from_json_bytes(cls, data: bytes) -> "BrregGroundTruth":
        return cls.from_dict(json.loads(data))


def load_truth_from_local(directory: str | Path) -> Dict[str, BrregGroundTruth]:
    """Load truth files from a local directory ``{orgnr}.json``."""
    directory = Path(directory)
    out: Dict[str, BrregGroundTruth] = {}
    for f in sorted(directory.glob("*.json")):
        gt = BrregGroundTruth.from_json_bytes(f.read_bytes())
        out[gt.orgnr] = gt
    return out


def load_truth_from_gcs(
    *,
    bucket: str = "sondre_brreg_data",
    prefix: str = "raw/ocr_eval_v2_10pdfs_300dpi/audit/brreg_ground_truth/",
    credentials_path: Optional[str] = None,
) -> Dict[str, BrregGroundTruth]:
    """Load truth files from GCS. Requires the ``gcs`` extra and a service
    account key with read access to the bucket."""
    try:
        from google.cloud import storage as gcs
        from google.oauth2 import service_account
    except ImportError as e:
        raise ImportError(
            "regnskapsnoter-eval[gcs] required. "
            "Install with `pip install regnskapsnoter-eval[gcs]`."
        ) from e

    if credentials_path:
        creds = service_account.Credentials.from_service_account_file(credentials_path)
        client = gcs.Client(project=creds.project_id, credentials=creds)
    else:
        client = gcs.Client()

    out: Dict[str, BrregGroundTruth] = {}
    for blob in client.list_blobs(bucket, prefix=prefix):
        if not blob.name.endswith(".json"):
            continue
        gt = BrregGroundTruth.from_json_bytes(blob.download_as_bytes())
        out[gt.orgnr] = gt
    return out


def truth_numbers(
    truth: Dict[str, BrregGroundTruth],
    *,
    drop_zero: bool = True,
) -> Dict[str, Set[int]]:
    """Distinct integer key_metrics per orgnr — the per-orgnr "truth set"."""
    out: Dict[str, Set[int]] = {}
    for orgnr, gt in truth.items():
        nums: Set[int] = set()
        for k, v in (gt.key_metrics or {}).items():
            if isinstance(v, (int, float)):
                n = int(round(v))
                if drop_zero and n == 0:
                    continue
                nums.add(n)
        out[orgnr] = nums
    return out
