import pytest
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell
from regnskapsnoter_eval.spatial import spatial_evidence


def cell(text, left, top, right, bottom):
    return TextCell(
        index=0, text=text, orig=text, from_ocr=True, confidence=1.0,
        rect=BoundingRectangle.from_bounding_box(BoundingBox(
            l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.TOPLEFT,
        )),
    )


@pytest.mark.parametrize("second", [
    cell("456", 0, 30, 30, 40),
    cell("456", 200, 0, 230, 10),
])
def test_separate_rows_or_columns_do_not_form_number(second):
    assert spatial_evidence([cell("123", 0, 0, 30, 10), second], {123456}) == []


def test_close_same_row_tokens_rejoin_in_spatial_order():
    cells = [cell("456", 35, 1, 65, 11), cell("123", 0, 0, 30, 10)]
    evidence = spatial_evidence(cells, {123456})
    assert evidence[0]["values"] == [123456]
    assert evidence[0]["cell_indices"] == [1, 0]
    assert evidence[0]["bbox"] == [0, 0, 65, 11]


def test_negative_sign_remains_attached():
    cells = [cell("-", 0, 0, 5, 10), cell("123", 8, 0, 38, 10)]
    assert spatial_evidence(cells, {123, -123})[0]["values"] == [-123]


def test_empty_page_has_no_evidence():
    assert spatial_evidence([], {123}) == []


def test_complete_value_in_single_line_cell():
    assert spatial_evidence([cell("Eiendeler 123 456", 0, 0, 100, 10)], {123456})[0]["values"] == [123456]


def test_short_minus_token_from_live_filing():
    cells = [
        cell("Netto", 433, 2584, 604, 2617),
        cell("finans", 646, 2580, 842, 2617),
        cell("-", 2279, 2600, 2298, 2607),
        cell("864", 2317, 2582, 2404, 2617),
        cell("-1", 2904, 2582, 2963, 2617),
        cell("347", 3004, 2582, 3100, 2617),
    ]
    evidence = spatial_evidence(cells, {-864, 864, -1347, -8641347})
    assert {n for item in evidence for n in item["values"]} == {-864, -1347}
    assert next(item for item in evidence if -864 in item["values"])["cell_indices"] == [2, 3]
