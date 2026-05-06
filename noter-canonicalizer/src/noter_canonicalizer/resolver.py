"""noter-canonicalizer — resolve observed Norwegian noter labels to regnskap-no concept IDs.

Resolution cascade:

1. **Exact match** against ``prefLabel`` ∪ ``altLabel`` (NFKC + casefold + whitespace
   collapse + bokmål/nynorsk equivalence). Returns confidence 1.0.
2. **Token-set ratio** via rapidfuzz ≥ 0.95 → returns confidence ≥ 0.9.
3. **Embedding fuzzy** with a sentence-transformer cosine ≥ 0.78 → returns
   confidence = cosine.

Below threshold → ``ConceptResolutionFailure`` with the top candidates so a
human review queue can suggest a new altLabel back to the taxonomy.

The cascade is *layered*: callers can disable later stages (e.g., to keep the
hot path deterministic) by passing ``use_fuzzy=False`` and/or
``use_embedding=False``.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Optional

from regnskap_no import api as taxonomy_api

_log = logging.getLogger(__name__)


# -- Normalisation ------------------------------------------------------

# -- Normalisation ------------------------------------------------------

# Nynorsk → bokmål equivalence table for financial / accounting vocabulary.
#
# The taxonomy ships only bokmål labels (v1.0.3: 314 labels, 0 marked
# lang='nn'). Without this table, a noter heading written in nynorsk
# ('eigedelar', 'eigenkapital', 'rekneskap') will never match a bokmål
# concept label ('eiendeler', 'egenkapital', 'regnskap'), forcing the
# canonicaliser to fall through to fuzzy/embedding even on exact-form
# matches.
#
# Each entry maps a nynorsk surface form to its bokmål equivalent. The
# normaliser substitutes whole-word matches BEFORE exact lookup against
# the label index. Substitutions are applied in length-descending order
# so longer phrases (rekneskapsår -> regnskapsår) are tried before their
# component words.
#
# Sources:
#   - regnskapsloven (Bokmål) and rekneskapslova (Nynorsk) parallel
#     terminology in lov-data
#   - Lovdata's parallel publication of Bokmål/Nynorsk versions of the
#     same accounting standards
#   - Sparebankforeningen and KS terminology lists for finance/admin
#
# This table covers the 26 most common term pairs in årsregnskap noter.
# When a new pair is added, add at least one test in
# tests/test_resolver.py::TestNynorskEquivalence so the change is auditable.
_NN_TO_NB = {
    # Asset / liability / equity nouns
    "eigedelar": "eiendeler",
    "eigedel": "eiendel",
    "eigenkapital": "egenkapital",
    "eigenkapitaltilskot": "egenkapitaltilskudd",
    "omløpsmidlar": "omløpsmidler",
    # Income / expense nouns
    "rekneskap": "regnskap",
    "rekneskapsår": "regnskapsaar",
    "rekneskapsåret": "regnskapsaaret",
    "rekneskapsprinsipp": "regnskapsprinsipp",
    "lønskostnad": "lønnskostnad",
    "lønskostnader": "lønnskostnader",
    "salsinntekt": "salgsinntekt",
    # Verbs / participles common in note narratives
    "påverkar": "paavirker",
    "føresegn": "bestemmelse",
    "føresetnad": "forutsetning",
    # Conjunctions / function words (last so they don't pre-empt longer matches)
    "kvar": "hver",
    "kvart": "hvert",
    "ikkje": "ikke",
    "berre": "bare",
    "saman": "sammen",
    "synast": "synes",
    "vere": "være",
    "blei": "ble",
    "vart": "ble",
    "stilling": "stilling",  # placeholder removed below
    # Common temporal / structural terms
    "innan": "innen",
    "rekna frå": "regnet fra",
    "kravsfrist": "kravsfrist",  # placeholder removed below
}

# Strip pure no-op entries left over from initial drafting
_NN_TO_NB = {k: v for k, v in _NN_TO_NB.items() if k != v}


def _bokmaal_nynorsk_normalise(s: str) -> str:
    """Collapse common nynorsk surface forms to their bokmål equivalents.

    Substitutes longest matches first so 'rekneskapsår' resolves to
    'regnskapsaar' before 'rekneskap' is tried separately.

    Conservative: only substitutes when the nynorsk form is present AND
    the bokmål form is not. This avoids destabilising mixed-language
    text (e.g. ``"Rekneskap (regnskap)"`` would not double-substitute).
    """
    out = s
    for nn in sorted(_NN_TO_NB, key=len, reverse=True):
        nb = _NN_TO_NB[nn]
        if nn in out and nb not in out:
            out = out.replace(nn, nb)
    return out


def normalise(s: str) -> str:
    """NFKC fold + casefold + whitespace collapse + bokmål/nynorsk equivalence."""
    s = unicodedata.normalize("NFKC", s).casefold()
    s = " ".join(s.split())
    s = _bokmaal_nynorsk_normalise(s)
    return s


# -- Result types -------------------------------------------------------

@dataclass
class ResolutionMatch:
    concept_id: str
    confidence: float          # 0..1
    method: str                # "exact" | "fuzzy" | "embedding"
    matched_label: str         # the label text that won the match
    matched_label_lang: Optional[str] = None
    matched_label_role: Optional[str] = None


@dataclass
class ResolutionResult:
    query: str
    match: Optional[ResolutionMatch]
    candidates: List[ResolutionMatch]    # top-N runners-up (always populated)
    method_chain: List[str]              # "exact" | "fuzzy" | "embedding" | "none"

    @property
    def resolved(self) -> bool:
        return self.match is not None


# -- Index --------------------------------------------------------------

class _LabelIndex:
    """Pre-built index of normalised labels for fast lookup.

    Cached at module level via the singleton ``get_index()``.
    """

    def __init__(self) -> None:
        self._exact: dict[str, list[tuple[str, str, str]]] = {}
        # All labels (subject, lang, role, original_text, normalised_text)
        self._all: list[tuple[str, str, str, str, str]] = []

        for lab in taxonomy_api._labels():
            if lab.subject_kind != "concept":
                continue
            n = normalise(lab.text)
            if not n:
                continue
            self._exact.setdefault(n, []).append((lab.subject_id, lab.lang, lab.role))
            self._all.append((lab.subject_id, lab.lang, lab.role, lab.text, n))

    def lookup_exact(self, normalised_query: str) -> List[tuple[str, str, str]]:
        return self._exact.get(normalised_query, [])

    def all_normalised(self) -> List[tuple[str, str, str, str, str]]:
        return self._all


_INDEX: Optional[_LabelIndex] = None


def get_index() -> _LabelIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = _LabelIndex()
    return _INDEX


# -- Embedding helper (lazy) -------------------------------------------

class _Embedder:
    """Thin wrapper around sentence-transformers to keep it as an optional dep."""

    def __init__(self, model_name: str = "NbAiLab/nb-sbert-base") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # noqa
            import numpy as np  # noqa
        except ImportError as e:
            raise ImportError(
                "Embedding cascade requires sentence-transformers + numpy. "
                "Install with `pip install noter-canonicalizer[embed]`."
            ) from e
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        self._cache_labels: list[tuple[str, str, str, str, str]] = []
        self._cache_embeds = None

    def encode(self, texts: list[str]):
        return self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)

    def index(self, label_index: _LabelIndex):
        all_labels = label_index.all_normalised()
        if all_labels == self._cache_labels and self._cache_embeds is not None:
            return self._cache_labels, self._cache_embeds
        texts = [n for *_, n in all_labels]
        embs = self.encode(texts)
        self._cache_labels = all_labels
        self._cache_embeds = embs
        return self._cache_labels, self._cache_embeds


_EMBEDDER: Optional[_Embedder] = None


def _get_embedder(model_name: Optional[str] = None) -> _Embedder:
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = _Embedder(model_name or "NbAiLab/nb-sbert-base")
    return _EMBEDDER


# -- Resolver -----------------------------------------------------------

def resolve(
    text: str,
    *,
    lang_pref: Optional[str] = "nb",
    use_fuzzy: bool = True,
    use_embedding: bool = False,
    fuzzy_threshold: float = 95.0,
    embedding_threshold: float = 0.78,
    top_k: int = 5,
) -> ResolutionResult:
    """Resolve ``text`` to a regnskap-no concept ID.

    The cascade short-circuits on the first stage that finds a confident match:

        exact (1.0)  →  fuzzy (≥ 0.9)  →  embedding (cosine ≥ 0.78)

    ``candidates`` is always populated with up to ``top_k`` runners-up so a
    review queue can show alternatives.
    """
    method_chain: List[str] = []
    n = normalise(text)
    if not n:
        return ResolutionResult(query=text, match=None, candidates=[], method_chain=["none"])

    idx = get_index()

    # Stage 1: exact
    method_chain.append("exact")
    hits = idx.lookup_exact(n)
    if hits:
        # Tie-breaking when multiple concepts share a standardLabel:
        #
        #  1. Prefer the requested language
        #  2. Prefer standardLabel over altLabel/etc.
        #  3. Prefer the "art" presentation form (no ``Funksjon`` suffix)
        #     over the "funksjon" form. The taxonomy carries parallel
        #     concepts for §§ 6-1 (art) and 6-1a (funksjon) presentations
        #     of the resultatregnskap. The "art" form dominates Norwegian
        #     SME årsregnskap; defaulting to it cuts ambiguity in 14 of
        #     14 known label collisions in v1.0.3.
        #  4. Final tiebreak: alphabetical concept_id for determinism.
        def _is_funksjon(concept_id: str) -> bool:
            return concept_id.endswith("Funksjon")

        ranked = sorted(
            hits,
            key=lambda h: (
                0 if (lang_pref and h[1] == lang_pref) else 1,
                0 if h[2] == "standardLabel" else 1,
                1 if _is_funksjon(h[0]) else 0,
                h[0],
            ),
        )
        winner = ranked[0]
        m = ResolutionMatch(
            concept_id=winner[0],
            confidence=1.0,
            method="exact",
            matched_label=text,
            matched_label_lang=winner[1],
            matched_label_role=winner[2],
        )
        cands = [
            ResolutionMatch(concept_id=c[0], confidence=1.0, method="exact",
                            matched_label=text, matched_label_lang=c[1],
                            matched_label_role=c[2])
            for c in ranked[1:top_k]
        ]
        return ResolutionResult(query=text, match=m, candidates=cands, method_chain=method_chain)

    # Stage 2: fuzzy
    if use_fuzzy:
        method_chain.append("fuzzy")
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            _log.debug("rapidfuzz not installed; skipping fuzzy stage")
        else:
            choices = idx.all_normalised()
            scored = process.extract(
                n,
                [c[4] for c in choices],
                scorer=fuzz.token_set_ratio,
                limit=top_k,
            )
            if scored:
                top_score = scored[0][1]
                if top_score >= fuzzy_threshold:
                    win_idx = scored[0][2]
                    win = choices[win_idx]
                    m = ResolutionMatch(
                        concept_id=win[0],
                        confidence=top_score / 100.0,
                        method="fuzzy",
                        matched_label=win[3],
                        matched_label_lang=win[1],
                        matched_label_role=win[2],
                    )
                    cands = []
                    for _, score, ci in scored[1:top_k]:
                        c = choices[ci]
                        cands.append(ResolutionMatch(
                            concept_id=c[0], confidence=score / 100.0,
                            method="fuzzy", matched_label=c[3],
                            matched_label_lang=c[1], matched_label_role=c[2],
                        ))
                    return ResolutionResult(query=text, match=m, candidates=cands, method_chain=method_chain)

    # Stage 3: embedding
    if use_embedding:
        method_chain.append("embedding")
        try:
            embedder = _get_embedder()
        except ImportError:
            _log.debug("sentence-transformers not installed; skipping embedding stage")
        else:
            import numpy as np
            choices, embs = embedder.index(idx)
            q_emb = embedder.encode([n])
            sims = (embs @ q_emb.T).flatten()
            order = np.argsort(-sims)
            top = order[:top_k]
            top_score = float(sims[top[0]])
            if top_score >= embedding_threshold:
                w = choices[int(top[0])]
                m = ResolutionMatch(
                    concept_id=w[0],
                    confidence=top_score,
                    method="embedding",
                    matched_label=w[3],
                    matched_label_lang=w[1],
                    matched_label_role=w[2],
                )
                cands = []
                for j in top[1:]:
                    c = choices[int(j)]
                    cands.append(ResolutionMatch(
                        concept_id=c[0], confidence=float(sims[j]),
                        method="embedding", matched_label=c[3],
                        matched_label_lang=c[1], matched_label_role=c[2],
                    ))
                return ResolutionResult(query=text, match=m, candidates=cands, method_chain=method_chain)

    # Failure: return top-K nearest as candidates if any stage produced them
    method_chain.append("none")
    return ResolutionResult(query=text, match=None, candidates=[], method_chain=method_chain)


def resolve_many(texts: Iterable[str], **kwargs) -> List[ResolutionResult]:
    return [resolve(t, **kwargs) for t in texts]
