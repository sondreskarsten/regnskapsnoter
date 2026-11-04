from types import SimpleNamespace
import pytest
from regnskapsnoter_pipeline.enrichment import enrich, _flatten_table_to_rows


def document(rows):
    grid = [[SimpleNamespace(text=text) for text in row] for row in rows]
    return SimpleNamespace(texts=[], tables=[SimpleNamespace(data=SimpleNamespace(grid=grid), prov=[])])


@pytest.mark.parametrize("header,values,selected,unresolved", [
    (["", "2025", "2024"], ["Eiendeler", "300", "250"], "300", ["250"]),
    (["", "2024", "2025"], ["Eiendeler", "250", "300"], "300", ["250"]),
    (["", "Note", "2025", "2024"], ["Eiendeler", "3", "300", "250"], "300", ["3", "250"]),
])
def test_only_requested_period_column_emits(header, values, selected, unresolved):
    result = enrich(document([header, values]), pdf_uri="fixture.pdf",
                    period_end="2025-12-31", use_fuzzy=False, validate=False)
    assert result.n_facts_emitted == 1
    assert result.annotations[0].body[1].value == selected
    assert [item["value_text"] for item in result.unresolved_values] == unresolved


@pytest.mark.parametrize("rows", [
    [["Eiendeler", "300", "250"]],
    [["", "2024", "2023"], ["Eiendeler", "300", "250"]],
    [["", "2025", "2025"], ["Eiendeler", "300", "250"]],
])
def test_ambiguous_or_absent_period_is_retained_without_emitting(rows):
    result = enrich(document(rows), pdf_uri="fixture.pdf",
                    period_end="2025-12-31", use_fuzzy=False, validate=False)
    assert result.n_facts_emitted == 0
    assert len(result.unresolved_values) == 2


def test_sparse_table_keeps_column_offsets():
    cells = [
        SimpleNamespace(text="Eiendeler", start_row_offset_idx=0, start_col_offset_idx=0),
        SimpleNamespace(text="300", start_row_offset_idx=0, start_col_offset_idx=3),
    ]
    table = SimpleNamespace(data=SimpleNamespace(table_cells=cells))
    assert _flatten_table_to_rows(table) == [["Eiendeler", "", "", "300"]]


def test_nested_grid_is_supported():
    doc = document([["Eiendeler", "300"]])
    assert _flatten_table_to_rows(doc.tables[0]) == [["Eiendeler", "300"]]
