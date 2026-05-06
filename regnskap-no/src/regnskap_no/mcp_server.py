"""MCP server — exposes regnskap-no as Model Context Protocol tools.

Audit C5 closed: ``regnskap_lookup_concept``, ``regnskap_resolve_label``,
and ``regnskap_validate_facts`` are now usable from any MCP-aware client
(Claude Desktop, Cursor, the docling-mcp suite, etc.).

Run as a stdio MCP server:

    python -m regnskap_no.mcp_server

Or wire it into Claude Desktop's mcpServers config:

    {
      "mcpServers": {
        "regnskap-no": {
          "command": "python",
          "args": ["-m", "regnskap_no.mcp_server"]
        }
      }
    }

Optional dependency: install the ``[mcp]`` extra to pull the MCP SDK
without polluting the base wheel.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _build_server():
    """Construct the FastMCP server with all three tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise ImportError(
            "regnskap-no MCP server requires the 'mcp' SDK. "
            "Install with: pip install regnskap-no[mcp]"
        ) from e

    from . import api

    server = FastMCP("regnskap-no")

    # ---- Tool 1: lookup_concept ----

    @server.tool()
    def regnskap_lookup_concept(concept_id: str) -> Dict[str, Any]:
        """Look up a single concept in the regnskap-no taxonomy.

        Returns concept metadata + all labels (every language and role)
        + calc-arc children (in any role) + reference text passages.

        Args:
            concept_id: full concept ID with prefix, e.g. ``regnskap-no:Eiendeler``.

        Returns:
            A dict with ``concept_id``, ``concept_kind``, ``labels``,
            ``calc_arcs``, ``references``. Returns an error key if the
            concept is unknown.
        """
        concept = api.get_concept(concept_id)
        if concept is None:
            return {"error": f"Unknown concept: {concept_id}"}

        labels = [
            {"text": l.text, "lang": l.lang, "role": l.role}
            for l in api.get_labels(concept_id)
        ]
        # Find calc-arcs across every role
        calc_arcs: List[Dict[str, Any]] = []
        for arc in api._calc_arcs():
            if arc.parent_id == concept_id:
                calc_arcs.append({
                    "role": arc.role,
                    "child": arc.child_id,
                    "weight": arc.weight,
                    "order": arc.order,
                })
        references = [
            {
                "publisher": r.publisher,
                "document": r.document,
                "paragraph": r.paragraph,
            }
            for r in api.get_references(concept_id)
        ]
        return {
            "concept_id": concept.concept_id,
            "namespace": concept.namespace,
            "balance": concept.balance,
            "period_type": concept.period_type,
            "data_type": concept.data_type,
            "abstract": concept.abstract,
            "labels": labels,
            "calc_arcs": calc_arcs,
            "references": references,
        }

    # ---- Tool 2: resolve_label ----

    @server.tool()
    def regnskap_resolve_label(
        text: str,
        lang_pref: Optional[str] = None,
        use_fuzzy: bool = True,
        use_embedding: bool = False,
    ) -> Dict[str, Any]:
        """Resolve a noter heading text to a regnskap-no concept ID.

        Runs the canonicaliser cascade: exact → fuzzy → optional embedding.
        Use this when you have a free-text label from an OCR'd årsregnskap
        and need to find which taxonomy concept it represents.

        Args:
            text: the free-text label (e.g. "Sum eiendeler", "Eigedelar totalt").
            lang_pref: 'nb', 'nn', or 'en' to prefer matches in that language
                when multiple concepts share a label.
            use_fuzzy: enable rapidfuzz-based fuzzy matching.
            use_embedding: enable the sentence-transformers embedding stage
                (requires the ``[embed]`` extra on noter-canonicalizer).

        Returns:
            Dict with ``resolved`` (bool), ``concept_id``, ``method``
            (exact/fuzzy/embedding), ``confidence``, ``method_chain``,
            ``candidates`` (top-k alternates).
        """
        try:
            from noter_canonicalizer import resolve
        except ImportError:
            return {"error": "noter-canonicalizer not installed"}

        result = resolve(
            text,
            lang_pref=lang_pref,
            use_fuzzy=use_fuzzy,
            use_embedding=use_embedding,
        )
        out: Dict[str, Any] = {
            "query": result.query,
            "resolved": result.resolved,
            "method_chain": list(result.method_chain),
        }
        if result.match:
            out["concept_id"] = result.match.concept_id
            out["method"] = result.match.method
            out["confidence"] = result.match.confidence
            out["matched_label"] = result.match.matched_label
            out["matched_label_lang"] = result.match.matched_label_lang
        out["candidates"] = [
            {
                "concept_id": c.concept_id,
                "method": c.method,
                "confidence": c.confidence,
                "matched_label": c.matched_label,
            }
            for c in result.candidates
        ]
        return out

    # ---- Tool 3: validate_facts ----

    @server.tool()
    def regnskap_validate_facts(facts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate a list of extracted facts against regnskap-no calc-arc rules.

        Each fact is ``{"concept_id": "regnskap-no:...", "value": float|str,
        "period_end": "YYYY-MM-DD"}``. The validator checks that calc-arc
        sums match (e.g. Eiendeler == Anleggsmidler + Omloepsmidler) within
        a small tolerance.

        Args:
            facts: list of fact dicts.

        Returns:
            ``{"conforms": bool, "n_passing": int, "n_failing": int,
              "failures": [{"rule": ..., "message": ...}]}``
        """
        try:
            from regnskapsnoter_shacl import validate_facts as _validate
            from regnskapsnoter_wadm import build_fact_annotation
        except ImportError as e:
            return {"error": f"validation requires regnskapsnoter-shacl + regnskapsnoter-wadm: {e}"}

        # Build proper Annotation objects from the input facts so the
        # validator can read concept_id, value, period_end out of the
        # WADM body fields.
        annotations = []
        for f in facts:
            try:
                ann = build_fact_annotation(
                    pdf_uri=f.get("pdf_uri", "urn:mcp:input"),
                    page_no=int(f.get("page_no", 1)),
                    bbox=tuple(f.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                    concept_id=str(f["concept_id"]),
                    value_text=str(f["value"]),
                    period_end=f.get("period_end"),
                )
                annotations.append(ann)
            except KeyError as ke:
                return {"error": f"missing required field {ke} in fact: {f}"}

        report = _validate(annotations)
        failures_out = []
        for ann, fails in report.failing:
            for f in fails:
                failures_out.append({
                    "rule": f.rule,
                    "message": f.message,
                })
        return {
            "conforms": report.conforms,
            "n_passing": len(report.passing),
            "n_failing": len(report.failing),
            "failures": failures_out,
        }

    return server


def main():
    """stdio entrypoint."""
    server = _build_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
