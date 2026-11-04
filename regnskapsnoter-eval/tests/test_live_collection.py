import json
import pytest
from regnskapsnoter_eval.live import select_reference, numeric_metrics

def record(year):
    return {"regnskapsperiode": {"tilDato": f"{year}-12-31"},
            "eiendeler": {"sumEiendeler": 1234, "flag": True}}

def test_wrong_year_never_falls_back():
    with pytest.raises(ValueError):
        select_reference(json.dumps([record(2025)]).encode(), [2024, 2025], 2024)

def test_matching_year_selected():
    assert select_reference(json.dumps([record(2024)]).encode(), [2024]) == record(2024)

def test_ambiguous_submission_rejected():
    with pytest.raises(ValueError):
        select_reference(json.dumps([record(2024), record(2024)]).encode(), [2024])

def test_reference_metrics_exclude_booleans():
    assert numeric_metrics(record(2024)) == {"eiendeler.sumEiendeler": 1234}


def test_latest_common_year_selected_from_multiple_records():
    raw = json.dumps([record(2023), record(2025), record(2024)]).encode()
    assert select_reference(raw, [2023, 2024, 2025]) == record(2025)
    assert select_reference(raw, [2023, 2024]) == record(2024)
