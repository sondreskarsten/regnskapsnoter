"""Tests for regnskapsnoter-migration.diff (audit C11)."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path

import pytest

from regnskapsnoter_migration import (
    DiffEntry,
    DriftReport,
    Fact,
    diff_facts,
    per_concept_drift,
    per_orgnr_summary,
    write_diff_parquet,
)


# Fixtures

def _v1_facts():
    return [
        Fact("811602892", "regnskap-no:Eiendeler", 300_000, "2024-12-31", "v1"),
        Fact("811602892", "regnskap-no:Anleggsmidler", 100_000, "2024-12-31", "v1"),
        Fact("811602892", "regnskap-no:Omlopsmidler", 200_000, "2024-12-31", "v1"),
        Fact("820246012", "regnskap-no:Eiendeler", 50_000, "2024-12-31", "v1"),
    ]


def _v2_facts():
    return [
        # Same value (agree)
        Fact("811602892", "regnskap-no:Eiendeler", 300_000, "2024-12-31", "v2"),
        # Different value (disagree)
        Fact("811602892", "regnskap-no:Anleggsmidler", 105_000, "2024-12-31", "v2"),
        # v2 missed Omloepsmidler entirely (v1_only)
        # New fact added by v2 (v2_only)
        Fact("811602892", "regnskap-no:Egenkapital", 75_000, "2024-12-31", "v2"),
        # Different orgnr — same value (agree)
        Fact("820246012", "regnskap-no:Eiendeler", 50_000, "2024-12-31", "v2"),
    ]


# ---- Fact dataclass ----

class TestFact:
    def test_construction(self):
        f = Fact("811602892", "regnskap-no:Eiendeler", 100.0, "2024-12-31")
        assert f.orgnr == "811602892"
        assert f.value == 100.0
        assert f.source == ""

    def test_frozen(self):
        f = Fact("811602892", "regnskap-no:Eiendeler", 100.0, "2024-12-31")
        with pytest.raises(Exception):
            f.value = 999

    def test_hashable(self):
        f1 = Fact("811602892", "regnskap-no:Eiendeler", 100.0, "2024-12-31")
        f2 = Fact("811602892", "regnskap-no:Eiendeler", 100.0, "2024-12-31")
        assert hash(f1) == hash(f2)


# ---- diff_facts ----

class TestDiffFacts:
    def test_returns_list_of_entries(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        assert isinstance(entries, list)
        assert all(isinstance(e, DiffEntry) for e in entries)

    def test_kinds_classified_correctly(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        kinds = sorted([(e.orgnr, e.concept_id, e.kind) for e in entries])
        # Expected:
        # 811602892 + Anleggsmidler -> disagree (100k vs 105k)
        # 811602892 + Egenkapital -> v2_only (new)
        # 811602892 + Eiendeler -> agree (300k both)
        # 811602892 + Omlopsmidler -> v1_only (v2 dropped)
        # 820246012 + Eiendeler -> agree (50k both)
        assert kinds == [
            ("811602892", "regnskap-no:Anleggsmidler", "disagree"),
            ("811602892", "regnskap-no:Egenkapital", "v2_only"),
            ("811602892", "regnskap-no:Eiendeler", "agree"),
            ("811602892", "regnskap-no:Omlopsmidler", "v1_only"),
            ("820246012", "regnskap-no:Eiendeler", "agree"),
        ]

    def test_disagree_carries_delta(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        anl = next(e for e in entries
                   if e.concept_id == "regnskap-no:Anleggsmidler")
        assert anl.kind == "disagree"
        assert anl.abs_delta == 5000.0   # |105_000 - 100_000|
        assert anl.rel_delta == pytest.approx(0.05)

    def test_agree_has_zero_delta(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        eien = next(
            e for e in entries
            if e.orgnr == "811602892" and e.concept_id == "regnskap-no:Eiendeler"
        )
        assert eien.kind == "agree"
        assert eien.abs_delta == 0.0
        assert eien.rel_delta == 0.0

    def test_v1_only_has_no_v2_value(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        oml = next(e for e in entries
                   if e.concept_id == "regnskap-no:Omlopsmidler")
        assert oml.kind == "v1_only"
        assert oml.v1_value == 200_000
        assert oml.v2_value is None
        assert oml.abs_delta is None
        assert oml.rel_delta is None

    def test_v2_only_has_no_v1_value(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        eg = next(e for e in entries
                  if e.concept_id == "regnskap-no:Egenkapital")
        assert eg.kind == "v2_only"
        assert eg.v1_value is None
        assert eg.v2_value == 75_000

    def test_empty_inputs(self):
        assert diff_facts([], []) == []

    def test_v2_empty_means_all_v1_only(self):
        entries = diff_facts(_v1_facts(), [])
        assert all(e.kind == "v1_only" for e in entries)
        assert len(entries) == len(_v1_facts())

    def test_v1_empty_means_all_v2_only(self):
        entries = diff_facts([], _v2_facts())
        assert all(e.kind == "v2_only" for e in entries)
        assert len(entries) == len(_v2_facts())

    def test_integer_rounding_treats_close_floats_as_agree(self):
        v1 = [Fact("a", "regnskap-no:X", 100.4, "2024-12-31")]
        v2 = [Fact("a", "regnskap-no:X", 100.3, "2024-12-31")]
        entries = diff_facts(v1, v2)
        assert entries[0].kind == "agree"

    def test_zero_v1_with_nonzero_v2_gives_inf_rel_delta(self):
        v1 = [Fact("a", "regnskap-no:X", 0, "2024-12-31")]
        v2 = [Fact("a", "regnskap-no:X", 100, "2024-12-31")]
        entries = diff_facts(v1, v2)
        assert entries[0].kind == "disagree"
        assert math.isinf(entries[0].rel_delta)

    def test_duplicate_keys_default_raises(self):
        v1 = [
            Fact("a", "regnskap-no:X", 100, "2024-12-31"),
            Fact("a", "regnskap-no:X", 200, "2024-12-31"),
        ]
        with pytest.raises(ValueError, match="duplicate fact key"):
            diff_facts(v1, [])

    def test_duplicate_keys_dedup_last(self):
        v1 = [
            Fact("a", "regnskap-no:X", 100, "2024-12-31"),
            Fact("a", "regnskap-no:X", 200, "2024-12-31"),
        ]
        v2 = [Fact("a", "regnskap-no:X", 200, "2024-12-31")]
        entries = diff_facts(v1, v2, dedup="last")
        assert entries[0].kind == "agree"
        assert entries[0].v1_value == 200

    def test_duplicate_keys_dedup_first(self):
        v1 = [
            Fact("a", "regnskap-no:X", 100, "2024-12-31"),
            Fact("a", "regnskap-no:X", 200, "2024-12-31"),
        ]
        v2 = [Fact("a", "regnskap-no:X", 100, "2024-12-31")]
        entries = diff_facts(v1, v2, dedup="first")
        assert entries[0].kind == "agree"
        assert entries[0].v1_value == 100


# ---- per_concept_drift ----

class TestPerConceptDrift:
    def test_aggregates_by_concept(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        report = per_concept_drift(entries)
        assert isinstance(report, DriftReport)
        # Eiendeler: 2 agrees (one per orgnr)
        assert report.rows["regnskap-no:Eiendeler"]["n_agree"] == 2
        # Anleggsmidler: 1 disagree
        assert report.rows["regnskap-no:Anleggsmidler"]["n_disagree"] == 1
        # Omlopsmidler: 1 v1_only
        assert report.rows["regnskap-no:Omlopsmidler"]["n_v1_only"] == 1
        # Egenkapital: 1 v2_only
        assert report.rows["regnskap-no:Egenkapital"]["n_v2_only"] == 1

    def test_agreement_rate(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        report = per_concept_drift(entries)
        # Eiendeler: 2 agree / (2 agree + 0 disagree) = 1.0
        assert report.agreement_rate("regnskap-no:Eiendeler") == 1.0
        # Anleggsmidler: 0 agree / 1 disagree = 0.0
        assert report.agreement_rate("regnskap-no:Anleggsmidler") == 0.0

    def test_agreement_rate_none_when_no_comparable(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        report = per_concept_drift(entries)
        # Omlopsmidler had only a v1_only entry — no comparable facts
        assert report.agreement_rate("regnskap-no:Omlopsmidler") is None

    def test_to_records_includes_agreement_rate(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        report = per_concept_drift(entries)
        recs = report.to_records()
        eien_rec = next(r for r in recs if r["key"] == "regnskap-no:Eiendeler")
        assert eien_rec["agreement_rate"] == 1.0


# ---- per_orgnr_summary ----

class TestPerOrgnrSummary:
    def test_aggregates_by_orgnr(self):
        entries = diff_facts(_v1_facts(), _v2_facts())
        report = per_orgnr_summary(entries)
        # 811602892: 1 agree (Eiendeler), 1 disagree (Anleggsmidler),
        # 1 v1_only (Omlopsmidler), 1 v2_only (Egenkapital)
        r = report.rows["811602892"]
        assert r == {
            "n_agree": 1, "n_disagree": 1,
            "n_v1_only": 1, "n_v2_only": 1,
        }
        # 820246012: 1 agree only
        assert report.rows["820246012"]["n_agree"] == 1


# ---- write_diff_parquet ----

class TestWriteDiffParquet:
    def test_writes_parquet_with_correct_row_count(self, tmp_path):
        entries = diff_facts(_v1_facts(), _v2_facts())
        out = tmp_path / "diff.parquet"
        n = write_diff_parquet(entries, str(out))
        assert n == len(entries)
        assert out.exists()

    def test_parquet_schema_has_expected_columns(self, tmp_path):
        import pyarrow.parquet as pq
        entries = diff_facts(_v1_facts(), _v2_facts())
        out = tmp_path / "diff.parquet"
        write_diff_parquet(entries, str(out))
        table = pq.read_table(str(out))
        cols = sorted(table.schema.names)
        assert cols == sorted([
            "orgnr", "concept_id", "period_end", "kind",
            "v1_value", "v2_value", "abs_delta", "rel_delta",
        ])

    def test_parquet_round_trip_preserves_kinds(self, tmp_path):
        import pyarrow.parquet as pq
        entries = diff_facts(_v1_facts(), _v2_facts())
        out = tmp_path / "diff.parquet"
        write_diff_parquet(entries, str(out))
        table = pq.read_table(str(out))
        kinds_back = sorted(table["kind"].to_pylist())
        kinds_orig = sorted(e.kind for e in entries)
        assert kinds_back == kinds_orig

    def test_parquet_handles_inf_rel_delta(self, tmp_path):
        v1 = [Fact("a", "regnskap-no:X", 0, "2024-12-31")]
        v2 = [Fact("a", "regnskap-no:X", 100, "2024-12-31")]
        entries = diff_facts(v1, v2)
        out = tmp_path / "diff.parquet"
        write_diff_parquet(entries, str(out))
        # Round-trip without crashing on inf
        import pyarrow.parquet as pq
        table = pq.read_table(str(out))
        rel = table["rel_delta"].to_pylist()
        assert math.isinf(rel[0])

    def test_empty_entries_writes_zero_rows(self, tmp_path):
        out = tmp_path / "diff.parquet"
        n = write_diff_parquet([], str(out))
        assert n == 0
        assert out.exists()
