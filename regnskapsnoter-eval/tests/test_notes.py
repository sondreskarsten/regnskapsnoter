from test_scoring import _cell
from regnskapsnoter_eval.notes import note_candidates


def extract(lines):
    return note_candidates([_cell(text) for text in lines], page="sample.png", engine="tesseract")


def test_visually_checked_waag_heading_keeps_ambiguity():
    result = extract([
        "Noter 2023 for Waag Produksjoner AS org.nr. 813 322 072",
        "Note I Lønnskostnader, antall ansatte, godtgjørelser, lån til ansatte m.m.",
        "Lønninger 279 533 330 800",
        "Note 2 Anleggsmidler",
        "Bokført verdi 123 654",
    ])
    assert len(result) == 2
    assert result[0]["number_raw"] == "I"
    assert result[0]["number_candidate"] == 1
    assert result[0]["review_flags"] == ["ambiguous_I_or_1"]
    assert result[0]["heading_raw"].startswith("Note I ")
    assert result[0]["text"] == "Lønninger 279 533 330 800"
    assert result[0]["boundary"] == "next_heading"
    assert result[0]["source_cells"][0]["index"] == 1


def test_visually_checked_prose_bank_note_is_retained():
    prose = "Innestående midler på skattetrekkskonto (bundne midler) er kr 11 103."
    result = extract(["Note 4 Bankinnskudd", prose])
    assert len(result) == 1
    assert result[0]["text"] == prose
    assert result[0]["number_candidate"] == 4
    assert result[0]["boundary"] == "page_end_unverified"


def test_note_column_and_inline_reference_are_not_headings():
    assert extract(["Beløp i: NOK Note 2023 2022", "Se Note 4 for detaljer", "Note"]) == []


def test_empty_and_heading_only_pages_are_explicit():
    assert extract([]) == []
    result = extract(["Note 2 Anleggsmidler"])
    assert result[0]["text"] == ""
    assert result[0]["status"] == "unreviewed_candidate"
    assert result[0]["boundary"] == "page_end_unverified"


def test_split_heading_from_saved_brreg_template():
    result = extract(["Note", "1", "Regnskapsprinsipper", "Årsregnskapet er satt opp i samsvar med regnskapsloven."])
    assert len(result) == 1
    assert result[0]["heading_raw"] == "Note\n1\nRegnskapsprinsipper"
    assert result[0]["number_candidate"] == 1
    assert result[0]["review_flags"] == ["split_heading_candidate"]
    assert result[0]["text"].startswith("Årsregnskapet")
    assert [c["index"] for c in result[0]["source_cells"]] == [0, 1, 2, 3]


def test_split_note_column_followed_by_year_is_not_a_heading():
    assert extract(["Note", "2023", "Eiendeler"]) == []
