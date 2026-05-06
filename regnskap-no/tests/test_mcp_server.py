"""Tests for the regnskap-no MCP server (audit C5).

Verifies the three tools the audit promised — ``regnskap_lookup_concept``,
``regnskap_resolve_label``, ``regnskap_validate_facts`` — register with
FastMCP and produce sensible JSON-serialisable output for valid input.
"""
from __future__ import annotations

import asyncio
import json

import pytest


def _has_mcp() -> bool:
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_mcp(),
    reason="MCP SDK not installed (install with regnskap-no[mcp])",
)


def _server():
    from regnskap_no.mcp_server import _build_server
    return _build_server()


def _call(server, name: str, args: dict):
    """Synchronous wrapper around FastMCP's async call_tool.

    FastMCP returns a tuple (content_list, structured_dict). The structured
    dict wraps our actual return value under a "result" key. We unwrap to
    that so tests can assert directly on the tool's return shape.
    """
    async def _inner():
        return await server.call_tool(name, args)
    result = asyncio.run(_inner())
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, dict):
                # FastMCP wraps the tool's return value under "result"
                return item.get("result", item)
        # Fallback: parse the first content item as JSON
        for item in result[0]:
            if hasattr(item, "text"):
                try:
                    parsed = json.loads(item.text)
                    if isinstance(parsed, dict) and "result" in parsed:
                        return parsed["result"]
                    return parsed
                except Exception:
                    return {"raw": item.text}
    return result


# ---- Server construction ----

def test_server_builds_with_three_tools():
    server = _server()
    assert server.name == "regnskap-no"
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "regnskap_lookup_concept",
        "regnskap_resolve_label",
        "regnskap_validate_facts",
    }


# ---- regnskap_lookup_concept ----

class TestLookupConcept:
    def test_lookup_known_concept(self):
        server = _server()
        out = _call(server, "regnskap_lookup_concept",
                    {"concept_id": "regnskap-no:Eiendeler"})
        assert out["concept_id"] == "regnskap-no:Eiendeler"
        # At least one bokmål standardLabel
        labels = out["labels"]
        assert any(l["text"] == "Eiendeler" and l["lang"] == "nb"
                   and l["role"] == "standardLabel" for l in labels)

    def test_lookup_returns_calc_arcs(self):
        server = _server()
        out = _call(server, "regnskap_lookup_concept",
                    {"concept_id": "regnskap-no:Eiendeler"})
        # Eiendeler has calc-arc children (Anleggsmidler + Omloepsmidler)
        children = {arc["child"] for arc in out["calc_arcs"]}
        assert "regnskap-no:Anleggsmidler" in children
        assert "regnskap-no:Omlopsmidler" in children

    def test_lookup_unknown_concept(self):
        server = _server()
        out = _call(server, "regnskap_lookup_concept",
                    {"concept_id": "regnskap-no:NotARealThing"})
        assert "error" in out

    def test_lookup_includes_period_type_and_balance(self):
        server = _server()
        out = _call(server, "regnskap_lookup_concept",
                    {"concept_id": "regnskap-no:Eiendeler"})
        # period_type and balance are part of the schema even if None
        assert "period_type" in out
        assert "balance" in out


# ---- regnskap_resolve_label ----

class TestResolveLabel:
    def test_resolve_exact_label(self):
        server = _server()
        out = _call(server, "regnskap_resolve_label",
                    {"text": "Eiendeler", "use_fuzzy": False})
        assert out["resolved"] is True
        assert out["concept_id"] == "regnskap-no:Eiendeler"
        assert out["method"] == "exact"

    def test_resolve_nynorsk_input(self):
        """Audit B8 + C5: nynorsk inputs should resolve through the
        bokmål/nynorsk equivalence layer to the bokmål concept."""
        server = _server()
        out = _call(server, "regnskap_resolve_label",
                    {"text": "Eigedelar", "use_fuzzy": False})
        assert out["resolved"] is True
        assert out["concept_id"] == "regnskap-no:Eiendeler"

    def test_resolve_unresolvable_returns_failure_envelope(self):
        server = _server()
        out = _call(server, "regnskap_resolve_label",
                    {"text": "totally novel xyz", "use_fuzzy": False})
        assert out["resolved"] is False
        assert "candidates" in out

    def test_resolve_passes_lang_pref(self):
        server = _server()
        out = _call(server, "regnskap_resolve_label",
                    {"text": "Eiendeler", "lang_pref": "nb",
                     "use_fuzzy": False})
        assert out["matched_label_lang"] == "nb"


# ---- regnskap_validate_facts ----

class TestValidateFacts:
    def test_validate_balanced_facts(self):
        """Eiendeler = Anleggsmidler + Omloepsmidler → conforms."""
        server = _server()
        facts = [
            {"concept_id": "regnskap-no:Eiendeler", "value": 300,
             "period_end": "2024-12-31"},
            {"concept_id": "regnskap-no:Anleggsmidler", "value": 100,
             "period_end": "2024-12-31"},
            {"concept_id": "regnskap-no:Omlopsmidler", "value": 200,
             "period_end": "2024-12-31"},
        ]
        out = _call(server, "regnskap_validate_facts", {"facts": facts})
        assert "n_passing" in out
        assert out["n_passing"] >= 1   # at least the parent passes
        # Failures dict must be JSON-serialisable
        json.dumps(out)

    def test_validate_unbalanced_facts_flags_failure(self):
        """100 + 200 ≠ 999 — calc-arc check fails."""
        server = _server()
        facts = [
            {"concept_id": "regnskap-no:Eiendeler", "value": 999,
             "period_end": "2024-12-31"},
            {"concept_id": "regnskap-no:Anleggsmidler", "value": 100,
             "period_end": "2024-12-31"},
            {"concept_id": "regnskap-no:Omlopsmidler", "value": 200,
             "period_end": "2024-12-31"},
        ]
        out = _call(server, "regnskap_validate_facts", {"facts": facts})
        assert out["n_failing"] >= 1
        assert out["conforms"] is False
        # Each failure has a rule + message
        for f in out["failures"]:
            assert "rule" in f and "message" in f

    def test_validate_missing_concept_id_returns_error(self):
        server = _server()
        facts = [{"value": 100, "period_end": "2024-12-31"}]
        out = _call(server, "regnskap_validate_facts", {"facts": facts})
        assert "error" in out


# ---- ImportError handling ----

def test_lookup_works_without_optional_deps():
    """The lookup tool only depends on regnskap_no.api, which is core."""
    # Just verify it doesn't raise
    server = _server()
    out = _call(server, "regnskap_lookup_concept",
                {"concept_id": "regnskap-no:Eiendeler"})
    assert "concept_id" in out
