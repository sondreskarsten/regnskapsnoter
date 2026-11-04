from regnskapsnoter_eval.scoring import score_page_consensus
from test_scoring import _cell


def test_digits_on_different_pages_do_not_form_a_number():
    reports = score_page_consensus(
        orgnr="111", per_voter_pages={"ocr": [[_cell("123")], [_cell("456")]]},
        truth={123456, 123, 456}, min_voters_for_reliable=1,
    )
    hits = {r.truth_value: r.n_hit for r in reports}
    assert hits == {123: 1, 456: 1, 123456: 0}


def test_split_tokens_on_same_page_remain_supported():
    reports = score_page_consensus(
        orgnr="111", per_voter_pages={"ocr": [[_cell("123"), _cell("456")]]},
        truth={123456}, min_voters_for_reliable=1,
    )
    assert reports[0].n_hit == 1


def test_empty_engine_set_is_not_unanimous():
    reports = score_page_consensus(
        orgnr="111", per_voter_pages={}, truth={123}, min_voters_for_reliable=1,
    )
    assert not reports[0].unanimous
    assert not reports[0].reliable
