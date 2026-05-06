"""LLM-driven typed extraction of regnskap-no facts from text.

Audit C7 closed: takes a noter text passage + a target concept set,
builds a Pydantic schema from regnskap_no.prompts, calls an LLM to
extract structured JSON conforming to that schema, returns parsed facts.

Public API:

    from regnskap_no.extract import (
        Fact,
        extract_calc_arc,
        extract_facts,
        GeminiClient,
    )

    facts = extract_calc_arc(
        text=noter_text,
        parent_concept="regnskap-no:Eiendeler",
        role="[620000] Balanse",
        period_end="2024-12-31",
        client=GeminiClient(),
    )

The LLM client is injectable: pass any callable that accepts
``(prompt: str, response_schema: dict) → dict`` to ``client=`` for tests
or to swap providers (Claude, GPT, Llama, etc.).

GeminiClient defaults to ``gemini-2.5-flash`` with ``thinkingBudget: 0``
and ``temperature: 0.0`` per Sondre's project conventions (see project
memory).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel


# ---- Fact dataclass (separate from regnskapsnoter_migration.Fact) ----

@dataclass
class Fact:
    """One extracted fact ready for downstream use.

    Attributes:
        concept_id: full prefixed regnskap-no ID.
        value: numeric value (None if the LLM returned null / missing).
        period_end: ISO period end.
        source_text: snippet from the LLM's input that motivated the
            extraction (best-effort; LLM-dependent).
    """

    concept_id: str
    value: Optional[float]
    period_end: str
    source_text: Optional[str] = None


# ---- LLM client protocol + Gemini default ----

LlmCallable = Callable[[str, Dict[str, Any]], Dict[str, Any]]
"""A function that takes (prompt, response_schema) and returns a dict
matching the schema. Test doubles + production clients both implement
this signature.
"""


class GeminiClient:
    """Default LLM client backed by Vertex AI Gemini.

    Uses gemini-2.5-flash with thinkingBudget=0 and temperature=0.0 per
    project convention. Reads credentials from
    ``GOOGLE_APPLICATION_CREDENTIALS`` env var.
    """

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-flash",
        location: str = "us-central1",
        project_id: Optional[str] = None,
    ):
        self.model = model
        self.location = location
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")

    def __call__(self, prompt: str, response_schema: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import google.auth
            import google.auth.transport.requests
            import requests
        except ImportError as e:
            raise ImportError(
                "GeminiClient requires google-auth + requests. "
                "Install with: pip install google-auth requests"
            ) from e

        creds, project = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())
        project = self.project_id or project

        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/"
            f"projects/{project}/locations/{self.location}/"
            f"publishers/google/models/{self.model}:generateContent"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
                "temperature": 0.0,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        payload = r.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)


# ---- Prompt construction ----

def _build_prompt(text: str, schema_doc: str) -> str:
    """Build the extraction prompt.

    The prompt structure is intentionally simple: input text + the schema
    documentation (auto-generated from the Pydantic model). No few-shot
    examples — the schema constraint via responseSchema does the work.
    """
    return (
        "You are extracting financial facts from Norwegian årsregnskap "
        "noter text. Output ONLY a JSON object matching the provided "
        "schema. Use null for any value not present in the text.\n\n"
        f"Schema:\n{schema_doc}\n\n"
        f"Noter text:\n{text}\n\n"
        "JSON output:"
    )


def _schema_to_dict(model: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model to the JSON Schema dict Gemini accepts."""
    return model.model_json_schema()


def _facts_from_extraction(
    extraction: Dict[str, Any],
    *,
    model: Type[BaseModel],
    period_end: str,
) -> List[Fact]:
    """Walk the parsed Pydantic instance and emit one Fact per non-null field.

    The concept_id for each field is encoded in the field's ``description``
    by ``regnskap_no.prompts.pydantic_for_calc_arc``, formatted as e.g.
    ``"regnskap-no:Anleggsmidler (weight=1.0)"`` or
    ``"regnskap-no:Eiendeler (computed total)"``. We parse the prefix off
    the description.

    The synthetic ``sum_total`` field representing the computed parent is
    skipped — only child facts are emitted.
    """
    instance = model(**extraction)
    facts: List[Fact] = []

    for field_name in type(instance).model_fields:
        field_info = type(instance).model_fields[field_name]
        value = getattr(instance, field_name)
        if value is None:
            continue
        # Skip the synthetic computed-parent field
        if field_name == "sum_total":
            continue
        # Parse concept_id from the description ("regnskap-no:X (weight=...)")
        concept_id: Optional[str] = None
        desc = field_info.description or ""
        if desc.startswith("regnskap-no:"):
            # Strip the trailing parenthetical
            paren_idx = desc.find(" (")
            concept_id = desc[:paren_idx] if paren_idx > -1 else desc.strip()
        # Fallback: synthesise from field name (lossy)
        if not concept_id:
            concept_id = f"regnskap-no:{field_name}"

        facts.append(Fact(
            concept_id=concept_id,
            value=float(value),
            period_end=period_end,
        ))
    return facts


# ---- Public extraction functions ----

def extract_calc_arc(
    text: str,
    *,
    parent_concept: str,
    role: str,
    period_end: str,
    client: LlmCallable,
) -> List[Fact]:
    """Extract all child facts of a calc arc from a noter text.

    Args:
        text: the noter passage (typically one section of the årsregnskap).
        parent_concept: prefixed regnskap-no concept ID (e.g.
            ``regnskap-no:Eiendeler``).
        role: the calc-arc role (presentation context, e.g. ``[620000] Balanse``).
        period_end: ISO period end attached to all extracted facts.
        client: any LlmCallable. Use ``GeminiClient()`` in production or
            a closure that returns canned JSON in tests.

    Returns:
        List of Fact, one per child concept in the calc arc that the LLM
        was able to extract. Children the LLM left as null are dropped.
    """
    from regnskap_no.prompts import pydantic_for_calc_arc

    model_cls = pydantic_for_calc_arc(parent_concept, role=role)
    schema = _schema_to_dict(model_cls)
    prompt = _build_prompt(text, json.dumps(schema, indent=2))

    extracted = client(prompt, schema)
    return _facts_from_extraction(
        extracted, model=model_cls, period_end=period_end,
    )


def extract_facts(
    text: str,
    *,
    target_model: Type[BaseModel],
    period_end: str,
    client: LlmCallable,
) -> List[Fact]:
    """Generic extraction: caller supplies any Pydantic model from prompts.

    Use this when you've already built a hypercube, axis-dict, or custom
    schema and want the LLM to fill it from text.
    """
    schema = _schema_to_dict(target_model)
    prompt = _build_prompt(text, json.dumps(schema, indent=2))
    extracted = client(prompt, schema)
    return _facts_from_extraction(
        extracted, model=target_model, period_end=period_end,
    )
