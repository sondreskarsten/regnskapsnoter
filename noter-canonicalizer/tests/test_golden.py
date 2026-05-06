"""Golden contract test for the canonicalizer.

The integration design promised: ``regnskap-no`` ships a "golden" set of 50
(label, expected_concept_id) pairs in test-only data; the canonicaliser
must hit ≥ 95% on this set in CI; any taxonomy SemVer-major bump must
keep these green or include a documented migration.

This file enforces that contract. The set is the first 50 standardLabel/nb
concepts in deterministic alphabetical order over concept_id, so it
covers the same vocabulary every test run.

When the taxonomy version advances, regenerate the set with the build
script in this file and bump the canonicalizer's compatibility version.

Audit C10 closed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from noter_canonicalizer import resolve


GOLDEN_FILE = Path(__file__).parent / "data" / "golden_set.json"


@pytest.fixture(scope="module")
def golden():
    with open(GOLDEN_FILE) as f:
        return json.load(f)


def test_golden_file_present_and_well_formed(golden):
    assert "items" in golden
    assert "version" in golden
    items = golden["items"]
    assert len(items) == 50
    for item in items:
        assert "label" in item
        assert "concept_id" in item
        assert item["concept_id"].startswith("regnskap-no:")


def test_canonicalizer_hits_95_percent_recall_on_golden(golden):
    """The contract: at least 95% of golden labels resolve to the right concept."""
    items = golden["items"]
    correct = 0
    wrong: list[tuple[str, str, str]] = []
    unresolved: list[str] = []
    for item in items:
        r = resolve(item["label"], lang_pref="nb",
                    use_fuzzy=True, use_embedding=False)
        if not r.resolved:
            unresolved.append(item["label"])
            continue
        if r.match.concept_id == item["concept_id"]:
            correct += 1
        else:
            wrong.append((item["label"], item["concept_id"], r.match.concept_id))
    recall = correct / len(items)
    msg = (
        f"Recall {recall:.1%} ({correct}/{len(items)}) — required ≥ 95%.\n"
        f"  unresolved ({len(unresolved)}): {unresolved[:5]}\n"
        f"  wrong ({len(wrong)}): "
        + "; ".join(f"{lbl!r}→{got} (expected {exp})" for lbl, exp, got in wrong[:5])
    )
    assert recall >= 0.95, msg


def test_canonicalizer_exact_recall_on_golden_no_fuzzy(golden):
    """With fuzzy off the labels are by construction in the index — must hit 100%."""
    items = golden["items"]
    miss = []
    for item in items:
        r = resolve(item["label"], lang_pref="nb", use_fuzzy=False, use_embedding=False)
        if not (r.resolved and r.match.concept_id == item["concept_id"]):
            miss.append(item)
    assert miss == [], f"exact-stage miss on {len(miss)} golden items: {miss[:3]}"


def test_canonicalizer_method_is_exact_for_unmodified_labels(golden):
    """Every standardLabel in the index must hit the EXACT stage —
    a fuzzy match would mean we lost an exact entry somehow."""
    items = golden["items"]
    fuzzy_count = 0
    for item in items:
        r = resolve(item["label"], lang_pref="nb",
                    use_fuzzy=True, use_embedding=False)
        if r.resolved and r.match.method != "exact":
            fuzzy_count += 1
    # All 50 should hit exactly. Allow zero tolerance.
    assert fuzzy_count == 0, (
        f"{fuzzy_count} golden labels needed fuzzy fallback — "
        "the exact-match index is incomplete or normalisation is broken"
    )
