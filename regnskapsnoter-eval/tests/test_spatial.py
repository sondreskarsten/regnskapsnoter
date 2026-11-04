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
