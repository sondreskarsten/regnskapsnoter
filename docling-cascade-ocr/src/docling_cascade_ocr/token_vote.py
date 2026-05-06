"""Token-level voting — granularity-independent.

Solves the *voter granularity mismatch* problem: line-mode voters (TesseractVoter,
ocrmypdf) emit one cell per line, word-mode voters (TesseractTsv, paddleocr,
easyocr per-word) emit one cell per word. Bbox-cluster voting (in ``vote.py``)
fails between heterogeneous-granularity voters because their bbox shapes don't
overlap at the same IoU threshold — a line bbox and the word bboxes inside it
do not cluster together cleanly.

This module votes on **values**, not on cell positions. Each voter contributes
the *set of normalised tokens* it observed across all its cells, and tokens
agreed on by ≥ N voters become consensus.

This is the abstraction the ocr-cascade-eval v2 audit used to compute its
"99/100 reliable" claim: each engine was reduced to "the set of integers it
transcribed in its raw text", and the union was voted on per-truth-value.

Two token universes:

- **Numeric tokens**: integers extracted via :func:`extract_numeric_tokens`.
  This is the primary universe for financial-statement reliability scoring.

- **Word tokens**: lowercase, NFKC-folded, punctuation-stripped word tokens
  extracted via :func:`extract_word_tokens`. Useful for label vocabulary
  voting (e.g. "did ≥ 5 voters see 'eiendeler'?").

Bboxes are still attached to consensus tokens, but as METADATA — the bbox is
"any voter's bbox where this token was observed", picked deterministically
(highest-confidence voter, then alphabetical voter name as tiebreak).
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell


# -- Token extractors --------------------------------------------------

# Norwegian numeric token: optional sign, then digits with optional thin-space
# / non-breaking-space / regular-space thousands grouping. Example matches:
#   "1234567"
#   "1 234 567"
#   "12 345 678"
#   "-90 488"
#   "(90 488)"  → handled by the parenthesised-negative pre-pass
# We do NOT match decimals — financial-statement key_metrics in NOK are integers.
_NUM_RE = re.compile(
    r"(?<!\w)(-?)(\d{1,3}(?:[\s\u00a0\u202f\u2009]\d{3})+|\d+)(?!\w)"
)
_PAREN_NEG_RE = re.compile(r"\(\s*(\d{1,3}(?:[\s\u00a0\u202f\u2009]\d{3})+|\d+)\s*\)")
_WORD_RE = re.compile(r"[A-Za-z\u00c0-\u017f]+")


def _normalise_minus(s: str) -> str:
    """Normalise Unicode minus / hyphen variants to ASCII hyphen."""
    for ch in "\u2010\u2011\u2012\u2013\u2014\u2212":
        s = s.replace(ch, "-")
    return s


def _digits_to_int(raw: str) -> int:
    """Strip Norwegian thousands separators and convert to int."""
    return int(re.sub(r"[\s\u00a0\u202f\u2009]", "", raw))


def extract_numeric_tokens(text: str) -> Set[int]:
    """Return the set of distinct signed integers found in ``text``.

    Handles:
    - grouped Norwegian thousands (``"1 234 567"``)
    - digit-only (``"1234567"``)
    - sign: ASCII minus, Unicode minus, or surrounding parentheses

    Tokens of value 0 are excluded — they're too noisy to vote on.
    """
    text = _normalise_minus(text)
    out: Set[int] = set()

    # Parenthesised negatives first; mask their span so they don't double-count
    # as positives in the unsigned scan below.
    masked = list(text)
    for m in _PAREN_NEG_RE.finditer(text):
        try:
            v = -_digits_to_int(m.group(1))
        except ValueError:
            continue
        if v != 0:
            out.add(v)
        for i in range(m.start(), m.end()):
            masked[i] = " "
    text_for_scan = "".join(masked)

    for m in _NUM_RE.finditer(text_for_scan):
        try:
            v = _digits_to_int(m.group(2))
        except ValueError:
            continue
        if m.group(1) == "-":
            v = -v
        if v != 0:
            out.add(v)
    return out


def extract_word_tokens(text: str, *, min_len: int = 2) -> Set[str]:
    """Return the set of lowercase NFKC-folded word tokens in ``text``.

    Excludes tokens shorter than ``min_len`` (default 2) to drop OCR noise
    (single-letter splits like "S", "A" from broken text).
    """
    text = unicodedata.normalize("NFKC", text)
    return {
        m.group(0).casefold()
        for m in _WORD_RE.finditer(text)
        if len(m.group(0)) >= min_len
    }


# -- Cell-to-text aggregation -----------------------------------------

def _join_cells_by_line(cells: List[TextCell], *, y_tolerance: float = 0.5) -> str:
    """Group cells into lines by their y-coordinate, then join each line.

    This is what makes token voting robust across granularity differences:

    - A line-mode voter that already has one cell per line: each cell forms
      its own line; output is identical to ``"\\n".join(cells)``.

    - A word-mode voter with N cells on one line: cells get grouped into
      one line and joined with a single space. So word-level
      ``["12", "345", "678"]`` becomes ``"12 345 678"`` — a single grouped
      numeric token that votes against the line-mode voter's
      ``"12 345 678"``.

    Lines are detected by binning y-centroids: two cells share a line when
    their y-centroids differ by ≤ ``y_tolerance × min(cell_height)``. Cells
    within a line are sorted left-to-right by x-centroid before joining.

    Returns one line per text-line, separated by ``\\n``.
    """
    if not cells:
        return ""

    def _ycenter(c: TextCell) -> float:
        bb = c.rect.to_bounding_box()
        return (bb.t + bb.b) / 2.0

    def _xcenter(c: TextCell) -> float:
        bb = c.rect.to_bounding_box()
        return (bb.l + bb.r) / 2.0

    def _height(c: TextCell) -> float:
        bb = c.rect.to_bounding_box()
        return abs(bb.b - bb.t)

    # Cells sorted by y first
    sorted_cells = sorted(cells, key=_ycenter)
    lines: List[List[TextCell]] = []
    for cell in sorted_cells:
        h = max(1.0, _height(cell))
        yc = _ycenter(cell)
        # Try to merge into the most recent line whose mean y is within tolerance
        if lines:
            last_line = lines[-1]
            last_yc = sum(_ycenter(c) for c in last_line) / len(last_line)
            last_h = sum(max(1.0, _height(c)) for c in last_line) / len(last_line)
            tol = y_tolerance * min(h, last_h)
            if abs(yc - last_yc) <= tol:
                last_line.append(cell)
                continue
        lines.append([cell])

    out_lines = []
    for line in lines:
        line.sort(key=_xcenter)
        out_lines.append(" ".join(c.text for c in line))
    return "\n".join(out_lines)


# -- Voter snapshot ----------------------------------------------------

@dataclass
class VoterTokens:
    """A voter's contribution to the token-level vote.

    ``cells`` retains the original TextCells so we can reconstruct bboxes
    and confidences for consensus tokens after voting.
    """

    voter: str
    cells: List[TextCell] = field(default_factory=list)
    full_text: str = ""
    numeric_tokens: Set[int] = field(default_factory=set)
    word_tokens: Set[str] = field(default_factory=set)

    @classmethod
    def from_cells(cls, voter: str, cells: List[TextCell]) -> "VoterTokens":
        text = _join_cells_by_line(cells)
        return cls(
            voter=voter,
            cells=cells,
            full_text=text,
            numeric_tokens=extract_numeric_tokens(text),
            word_tokens=extract_word_tokens(text),
        )


# -- Token-level vote --------------------------------------------------

@dataclass
class NumericConsensus:
    """A numeric token agreed on by ≥ ``min_voters`` voters."""

    value: int
    voters_hit: List[str]
    voters_attempted: List[str]
    n_hit: int
    n_attempted: int
    unanimous: bool
    sample_cell: Optional[TextCell] = None

    def to_dict(self) -> dict:
        bb = self.sample_cell.rect.to_bounding_box() if self.sample_cell else None
        return {
            "value": self.value,
            "voters_hit": list(self.voters_hit),
            "voters_attempted": list(self.voters_attempted),
            "n_hit": self.n_hit,
            "n_attempted": self.n_attempted,
            "unanimous": self.unanimous,
            "sample_bbox": [bb.l, bb.t, bb.r, bb.b] if bb else None,
            "sample_text": self.sample_cell.text if self.sample_cell else None,
            "sample_confidence": self.sample_cell.confidence if self.sample_cell else None,
        }


@dataclass
class WordConsensus:
    """A word token agreed on by ≥ ``min_voters`` voters."""

    token: str
    voters_hit: List[str]
    voters_attempted: List[str]
    n_hit: int
    n_attempted: int
    unanimous: bool

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "voters_hit": list(self.voters_hit),
            "voters_attempted": list(self.voters_attempted),
            "n_hit": self.n_hit,
            "n_attempted": self.n_attempted,
            "unanimous": self.unanimous,
        }


@dataclass
class TokenVoteResult:
    """Output of :func:`token_vote`."""

    numeric: List[NumericConsensus]
    words: List[WordConsensus]
    voters: List[str]
    n_voters: int

    @property
    def n_unanimous_numeric(self) -> int:
        return sum(1 for c in self.numeric if c.unanimous)

    @property
    def n_committed_numeric(self) -> int:
        return len(self.numeric)


def _value_to_norwegian_grouped(v: int) -> str:
    s = str(abs(v))
    s_rev = s[::-1]
    parts = [s_rev[i:i + 3][::-1] for i in range(0, len(s_rev), 3)][::-1]
    return ("-" if v < 0 else "") + " ".join(parts)


def _find_sample_cell_for_value(
    value: int, voter_tokens: Dict[str, VoterTokens], voters_hit: List[str],
) -> Optional[TextCell]:
    """Pick a representative cell for a consensus value.

    Strategy: among voters that observed this value, find the cell whose text
    contains the value; pick the highest-confidence one. Tiebreak by voter
    name alphabetical for determinism.
    """
    grouped = _value_to_norwegian_grouped(value)
    digits = ("-" if value < 0 else "") + str(abs(value))

    candidates: List[Tuple[float, str, TextCell]] = []
    for voter in sorted(voters_hit):
        vt = voter_tokens.get(voter)
        if vt is None:
            continue
        for cell in vt.cells:
            t = _normalise_minus(cell.text)
            if grouped in t or digits in t:
                candidates.append((-cell.confidence, voter, cell))  # neg for sort=high-conf-first
                break  # first hit per voter
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def token_vote(
    per_voter_cells: Dict[str, Iterable[TextCell]],
    *,
    min_voters_for_commit: int = 7,
    vote_words: bool = False,
) -> TokenVoteResult:
    """Token-level vote across heterogeneous-granularity voters.

    Args:
        per_voter_cells: ``{voter_name: list[TextCell]}``.
        min_voters_for_commit: a token is committed when ≥ this many voters
            observed it. Match the bbox-cluster threshold so the two votes
            agree on the same reliability bar.
        vote_words: also emit word-token consensus. Default off because most
            applications only care about numeric reliability.

    Returns:
        :class:`TokenVoteResult` with sorted lists.
    """
    voter_tokens: Dict[str, VoterTokens] = {
        v: VoterTokens.from_cells(v, list(cells))
        for v, cells in per_voter_cells.items()
    }
    voters = sorted(voter_tokens)
    n_voters = len(voters)

    # Numeric universe = union of all voters' numeric tokens
    all_numeric: Set[int] = set()
    for vt in voter_tokens.values():
        all_numeric.update(vt.numeric_tokens)

    numeric_consensus: List[NumericConsensus] = []
    for v in sorted(all_numeric):
        hits = [voter for voter in voters if v in voter_tokens[voter].numeric_tokens]
        if len(hits) < min_voters_for_commit:
            continue
        sample = _find_sample_cell_for_value(v, voter_tokens, hits)
        numeric_consensus.append(NumericConsensus(
            value=v,
            voters_hit=hits,
            voters_attempted=voters,
            n_hit=len(hits),
            n_attempted=n_voters,
            unanimous=len(hits) == n_voters,
            sample_cell=sample,
        ))

    word_consensus: List[WordConsensus] = []
    if vote_words:
        all_words: Set[str] = set()
        for vt in voter_tokens.values():
            all_words.update(vt.word_tokens)
        for w in sorted(all_words):
            hits = [voter for voter in voters if w in voter_tokens[voter].word_tokens]
            if len(hits) < min_voters_for_commit:
                continue
            word_consensus.append(WordConsensus(
                token=w,
                voters_hit=hits,
                voters_attempted=voters,
                n_hit=len(hits),
                n_attempted=n_voters,
                unanimous=len(hits) == n_voters,
            ))

    return TokenVoteResult(
        numeric=numeric_consensus,
        words=word_consensus,
        voters=voters,
        n_voters=n_voters,
    )


def consensus_to_textcells(result: TokenVoteResult) -> List[TextCell]:
    """Materialise the numeric consensus as TextCells for downstream consumers.

    Uses the sample cell when available (preserves the real bbox + confidence);
    falls back to a synthetic zero-area cell when no voter retained a usable
    bbox (very rare — only when all voters agreed on the value but produced
    differently-shaped cells that didn't survive the sample lookup).
    """
    out: List[TextCell] = []
    for i, c in enumerate(result.numeric):
        if c.sample_cell is not None:
            cell = c.sample_cell.model_copy(update={
                "index": i,
                "confidence": c.n_hit / max(1, c.n_attempted),
            })
            out.append(cell)
        else:
            # Synthetic placeholder
            out.append(TextCell(
                index=i,
                text=_value_to_norwegian_grouped(c.value),
                orig=str(c.value),
                from_ocr=True,
                confidence=c.n_hit / max(1, c.n_attempted),
                rect=BoundingRectangle.from_bounding_box(BoundingBox(
                    l=0, t=0, r=0, b=0, coord_origin=CoordOrigin.TOPLEFT,
                )),
            ))
    return out
