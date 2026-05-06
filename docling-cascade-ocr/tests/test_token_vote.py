"""Tests for token-level voting (granularity-independent).

Includes a regression test for the audit-discovered scenario:
TesseractVoter (line-mode) and TesseractTsvVoter (word-mode) produced 0
unanimous consensus under bbox-cluster voting because their bbox shapes
didn't overlap. Token voting must give a non-zero unanimous count on the
same input.
"""
from __future__ import annotations

import pytest

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from docling_cascade_ocr.token_vote import (
    NumericConsensus,
    TokenVoteResult,
    VoterTokens,
    WordConsensus,
    consensus_to_textcells,
    extract_numeric_tokens,
    extract_word_tokens,
    token_vote,
)


def _cell(text: str, *, l=0, t=0, r=10, b=10, conf=0.9) -> TextCell:
    return TextCell(
        index=0, text=text, orig=text, from_ocr=True, confidence=conf,
        rect=BoundingRectangle.from_bounding_box(BoundingBox(
            l=l, t=t, r=r, b=b, coord_origin=CoordOrigin.TOPLEFT,
        )),
    )


# -- extract_numeric_tokens --

class TestExtractNumeric:
    def test_grouped_with_spaces(self):
        assert extract_numeric_tokens("Sum 12 345 678 NOK") == {12345678}

    def test_grouped_with_nbsp(self):
        # Norwegian thousands separator can be a non-breaking space
        assert extract_numeric_tokens("12\u00a0345\u00a0678") == {12345678}

    def test_digit_only(self):
        assert extract_numeric_tokens("Sum 12345678 NOK") == {12345678}

    def test_negative_unicode_minus(self):
        assert extract_numeric_tokens("Sum \u221290 488") == {-90488}

    def test_negative_paren(self):
        assert extract_numeric_tokens("Sum (90 488)") == {-90488}

    def test_negative_ascii_minus(self):
        assert extract_numeric_tokens("Sum -90 488") == {-90488}

    def test_zero_excluded(self):
        # Zero is too noisy to be a useful vote token
        assert extract_numeric_tokens("Garantistillelser 0 0") == set()

    def test_multiple_distinct(self):
        text = "Sum eiendeler 12 345 og resultat 6 789"
        assert extract_numeric_tokens(text) == {12345, 6789}

    def test_dedup(self):
        # Same value mentioned twice → one token
        text = "Sum 1 234 og igjen 1234"
        assert extract_numeric_tokens(text) == {1234}

    def test_does_not_match_letters_inside(self):
        # 'abc123' should NOT match (not a clean number boundary)
        assert extract_numeric_tokens("abc123def") == set()


# -- extract_word_tokens --

class TestExtractWords:
    def test_simple(self):
        assert extract_word_tokens("Sum eiendeler") == {"sum", "eiendeler"}

    def test_norwegian_diacritics(self):
        # æøå are kept (within Latin Extended)
        out = extract_word_tokens("Omløpsmidler")
        assert "omløpsmidler" in out

    def test_min_len_filters_short(self):
        out = extract_word_tokens("X eiendeler", min_len=2)
        assert "x" not in out
        assert "eiendeler" in out

    def test_nfkc_normalisation(self):
        # 'eﬃcient' (ligature ﬃ) → 'efficient' under NFKC
        out = extract_word_tokens("eﬃcient")
        assert "efficient" in out


# -- VoterTokens --

class TestVoterTokens:
    def test_aggregates_across_cells(self):
        cells = [_cell("Sum 12 345"), _cell("og 6 789")]
        vt = VoterTokens.from_cells("v", cells)
        assert vt.numeric_tokens == {12345, 6789}
        assert "sum" in vt.word_tokens

    def test_keeps_cells(self):
        cells = [_cell("Sum 12 345")]
        vt = VoterTokens.from_cells("v", cells)
        assert vt.cells == cells


# -- token_vote (the regression test) --

class TestTokenVote:
    def test_unanimous_across_homogeneous_voters(self):
        """When every voter sees '12 345', it commits unanimously."""
        per_voter = {
            f"v{i}": [_cell("Sum 12 345 NOK")] for i in range(7)
        }
        result = token_vote(per_voter, min_voters_for_commit=7)
        assert len(result.numeric) == 1
        nc = result.numeric[0]
        assert nc.value == 12345
        assert nc.unanimous
        assert nc.n_hit == 7

    def test_skips_below_threshold(self):
        per_voter = {f"v{i}": [_cell("only 1234")] for i in range(3)}
        result = token_vote(per_voter, min_voters_for_commit=7)
        assert result.numeric == []

    def test_token_vote_works_across_line_and_word_granularities(self):
        """REGRESSION TEST FOR AUDIT B1.

        Voter A is line-mode: emits one cell per line of text.
        Voter B is word-mode: emits one cell per word.

        Bbox-cluster voting fails here because line bboxes and word bboxes
        don't overlap at IoU ≥ 0.3. Token voting must still work because
        ``_join_cells_by_line`` groups voter B's word cells back into a
        single line via y-coordinate clustering before tokenisation.

        Both voters end up contributing the grouped numeric token
        ``12345678`` to the universe, and the cascade produces a
        unanimous consensus.
        """
        # Voter A: one cell with the whole line
        line_cell = _cell("Sum eiendeler 12 345 678", l=0, t=0, r=400, b=20)
        voter_a = [line_cell]

        # Voter B: word cells, all on the same line (same y-band)
        voter_b = [
            _cell("Sum",       l=0,   t=2, r=40,  b=18),
            _cell("eiendeler", l=42,  t=2, r=160, b=18),
            _cell("12",        l=200, t=2, r=240, b=18),
            _cell("345",       l=242, t=2, r=290, b=18),
            _cell("678",       l=292, t=2, r=340, b=18),
        ]

        tv = token_vote(
            {"line": voter_a, "word": voter_b},
            min_voters_for_commit=2,
        )
        # The granularity mismatch is solved: both voters' line-aggregated
        # text contains "12 345 678", so the value 12345678 is in both
        # voters' numeric_tokens and is committed unanimously.
        unanimous_values = {nc.value for nc in tv.numeric if nc.unanimous}
        assert 12345678 in unanimous_values, (
            "Token vote failed to bridge line/word granularity mismatch — "
            "_join_cells_by_line is not regrouping word cells into lines."
        )

    def test_token_vote_keeps_lines_separate(self):
        """Two-line word voter: cells on different y-bands stay separate."""
        cells = [
            # Line 1
            _cell("Sum", l=0, t=2, r=40, b=18),
            _cell("eiendeler", l=42, t=2, r=160, b=18),
            _cell("12345", l=200, t=2, r=290, b=18),
            # Line 2 (y far below)
            _cell("Sum", l=0, t=200, r=40, b=216),
            _cell("gjeld", l=42, t=200, r=140, b=216),
            _cell("9876", l=200, t=200, r=290, b=216),
        ]
        from docling_cascade_ocr.token_vote import _join_cells_by_line
        text = _join_cells_by_line(cells)
        # Two distinct lines
        assert text.count("\n") == 1
        assert "Sum eiendeler 12345" in text
        assert "Sum gjeld 9876" in text


class TestConsensusToTextcells:
    def test_round_trip_preserves_sample_bbox(self):
        per_voter = {
            f"v{i}": [_cell("Sum 12 345", l=10, t=20, r=110, b=40, conf=0.8)]
            for i in range(7)
        }
        tv = token_vote(per_voter, min_voters_for_commit=7)
        cells = consensus_to_textcells(tv)
        assert len(cells) == 1
        cell = cells[0]
        # Should preserve a real bbox from a sample voter
        bb = cell.rect.to_bounding_box()
        assert bb.l == 10 and bb.t == 20

    def test_confidence_is_vote_share(self):
        per_voter = {f"v{i}": [_cell("1234")] for i in range(7)}
        per_voter["bad"] = [_cell("nothing")]
        tv = token_vote(per_voter, min_voters_for_commit=7)
        cells = consensus_to_textcells(tv)
        # 7 of 8 voters hit; conf = 7/8 = 0.875
        assert cells[0].confidence == pytest.approx(7 / 8)


class TestWordVoteOptional:
    def test_word_vote_disabled_by_default(self):
        per_voter = {f"v{i}": [_cell("Eiendeler")] for i in range(7)}
        tv = token_vote(per_voter, min_voters_for_commit=7)
        # Numeric vote runs; word vote disabled
        assert tv.words == []

    def test_word_vote_enabled(self):
        per_voter = {f"v{i}": [_cell("Eiendeler")] for i in range(7)}
        tv = token_vote(per_voter, min_voters_for_commit=7, vote_words=True)
        assert any(wc.token == "eiendeler" and wc.unanimous for wc in tv.words)
