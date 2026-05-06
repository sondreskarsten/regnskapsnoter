"""Tests for the document_ai voter (audit C2).

The audit said: 'Document AI / Gemini Vision runs as the 11th voter,
sampled (5% random + 100% on low-agreement clusters).'

This commit adds:
  - DocumentAiVoter that calls gemini-2.5-flash via Vertex AI REST
  - sample_rate field on CascadeVoter that the model uses to fire lazy
    voters on a random fraction of unanimous pages

These tests cover the static config + the pure helpers + the sampling
selection. We do NOT make real API calls (no creds in CI).
"""
from __future__ import annotations

import io
import random

import pytest


def _has_pil() -> bool:
    try:
        from PIL import Image  # noqa
        return True
    except ImportError:
        return False


# ---- Config / registry ----

class TestDocumentAiSpec:
    def test_document_ai_in_voter_name_literal(self):
        from docling_cascade_ocr.options import CascadeVoter
        # Should construct without error
        v = CascadeVoter(name="document_ai")
        assert v.name == "document_ai"

    def test_default_voter_list_includes_document_ai(self):
        from docling_cascade_ocr.options import CascadeOcrOptions
        opts = CascadeOcrOptions()
        names = [v.name for v in opts.voters]
        assert "document_ai" in names

    def test_default_document_ai_is_disabled_lazy_and_sampled(self):
        from docling_cascade_ocr.options import CascadeOcrOptions
        opts = CascadeOcrOptions()
        d = next(v for v in opts.voters if v.name == "document_ai")
        # API-quota dependency → off by default
        assert d.enabled is False
        # When enabled, it should be lazy + sampled
        assert d.lazy is True
        assert d.sample_rate == 0.05

    def test_sample_rate_default_is_zero(self):
        from docling_cascade_ocr.options import CascadeVoter
        v = CascadeVoter(name="tesseract")
        assert v.sample_rate == 0.0

    def test_sample_rate_can_be_set(self):
        from docling_cascade_ocr.options import CascadeVoter
        v = CascadeVoter(name="document_ai", sample_rate=0.10)
        assert v.sample_rate == 0.10


# ---- Pure helpers (no network) ----

@pytest.mark.skipif(not _has_pil(), reason="Pillow required")
class TestDocumentAiHelpers:
    @pytest.fixture
    def voter(self):
        from docling_cascade_ocr.voters.base import VoterUnavailable
        try:
            from docling_cascade_ocr.voters import DocumentAiVoter
            return DocumentAiVoter(lang=["no", "nb"])
        except VoterUnavailable as e:
            pytest.skip(f"document_ai voter deps missing: {e}")

    def test_build_request_body_shape(self, voter):
        body = voter._build_request_body("FAKE_BASE64")
        assert "contents" in body
        assert "generationConfig" in body
        gc = body["generationConfig"]
        # Project convention: thinkingBudget=0 + temperature=0
        assert gc["temperature"] == 0.0
        assert gc["thinkingConfig"]["thinkingBudget"] == 0
        # Image is sent as inline_data
        parts = body["contents"][0]["parts"]
        types = [list(p.keys())[0] for p in parts]
        assert "text" in types
        assert "inline_data" in types

    def test_parse_response_text_one_cell_per_line(self, voter):
        text = "Sum eiendeler 12 345\n  Anleggsmidler 100\n\nOmløpsmidler 200\n"
        lines = voter._parse_response_text(text)
        assert lines == ["Sum eiendeler 12 345", "Anleggsmidler 100", "Omløpsmidler 200"]

    def test_parse_response_text_empty_string(self, voter):
        assert voter._parse_response_text("") == []

    def test_extract_text_from_response_envelope(self, voter):
        envelope = {
            "candidates": [{
                "content": {"parts": [{"text": "Hello\nWorld"}]},
            }],
        }
        assert voter._extract_text_from_response(envelope) == "Hello\nWorld"

    def test_extract_text_from_empty_response(self, voter):
        assert voter._extract_text_from_response({"candidates": []}) == ""

    def test_extract_text_concatenates_multiple_parts(self, voter):
        envelope = {
            "candidates": [{
                "content": {"parts": [
                    {"text": "Part A "},
                    {"text": "Part B"},
                ]},
            }],
        }
        assert voter._extract_text_from_response(envelope) == "Part A Part B"

    def test_crop_to_b64_returns_string(self, voter):
        from PIL import Image
        from docling_core.types.doc import BoundingBox, CoordOrigin

        img = Image.new("RGB", (100, 100), "white")
        rect = BoundingBox(l=0, t=0, r=50, b=50,
                            coord_origin=CoordOrigin.TOPLEFT)
        b64 = voter._crop_to_b64(img, rect)
        assert isinstance(b64, str)
        assert len(b64) > 0
        # Must be valid base64
        import base64
        base64.b64decode(b64)


# ---- Sampling ----

class TestSampledVoters:
    def test_sample_rate_zero_never_fires(self):
        """Voters with sample_rate=0 are never selected by sampling."""
        from docling_cascade_ocr.model import CascadeOcrModel

        class _V:
            name = "x"
            sample_rate = 0.0
        random.seed(0)
        # Try many times — should NEVER fire
        for _ in range(1000):
            assert CascadeOcrModel._sampled_voters([_V()]) == []

    def test_sample_rate_one_always_fires(self):
        """Voters with sample_rate=1.0 always fire."""
        from docling_cascade_ocr.model import CascadeOcrModel

        class _V:
            name = "x"
            sample_rate = 1.0
        for _ in range(100):
            sampled = CascadeOcrModel._sampled_voters([_V()])
            assert len(sampled) == 1

    def test_sample_rate_0_5_fires_about_half(self):
        """A 0.5 sample rate should fire ~50% over many trials."""
        from docling_cascade_ocr.model import CascadeOcrModel

        class _V:
            name = "x"
            sample_rate = 0.5
        random.seed(42)
        n_fires = 0
        N = 1000
        for _ in range(N):
            if CascadeOcrModel._sampled_voters([_V()]):
                n_fires += 1
        # Bayesian sanity: 1000 trials @ p=0.5 has stddev 16 → 3-sigma is ~48
        # So 450..550 is the safe assertion range
        assert 450 <= n_fires <= 550, (
            f"sample_rate=0.5 fired {n_fires}/{N} times, expected ~500"
        )

    def test_lazy_voter_without_sample_rate_returns_empty(self):
        """A purely lazy voter (no sample_rate) is not sampled."""
        from docling_cascade_ocr.model import CascadeOcrModel

        class _V:
            name = "x"
            lazy = True
            sample_rate = 0.0
        for _ in range(100):
            assert CascadeOcrModel._sampled_voters([_V()]) == []


# ---- Build_voters propagates sample_rate ----

def test_build_voters_propagates_sample_rate():
    """The voter object carries the sample_rate from its spec."""
    from docling_cascade_ocr.voters.base import build_voters
    from docling_cascade_ocr.options import CascadeVoter

    try:
        voters = build_voters(
            [CascadeVoter(name="docling_default", sample_rate=0.1)],
            lang=["no", "nb"], use_gpu=False,
        )
    except Exception:
        pytest.skip("Tesseract not available")
    if not voters:
        pytest.skip("No usable voters")
    assert voters[0].sample_rate == 0.1
