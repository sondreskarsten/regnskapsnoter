"""W3C Web Annotation Data Model emitter for regnskap fact extractions.

Implements the JSON-LD shape from the artifact recommendation: every fact is
an Annotation whose target is a PDF bbox (FragmentSelector + SvgSelector +
TextQuoteSelector), whose body lists a SpecificResource pointing at the
regnskap-no concept and a TextualBody carrying the value, with namespaced
extensions for cascade vote and XBRL period/balance attributes.

Validates structurally via Pydantic. Serialises to JSON-LD with the
``http://www.w3.org/ns/anno.jsonld`` context plus the ``regnskap-no``
namespace. The output is genuine WADM and can be ingested by Annotorious,
Hypothes.is data stores, Recogito, etc.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from regnskap_no.api import get_concept

# ---- Core WADM types --------------------------------------------------

WADM_CONTEXT = "http://www.w3.org/ns/anno.jsonld"

# Selectors (subset relevant to PDF document targets)


class FragmentSelector(BaseModel):
    type: Literal["FragmentSelector"] = "FragmentSelector"
    value: str
    conformsTo: str = "http://www.w3.org/TR/media-frags/"


class SvgSelector(BaseModel):
    type: Literal["SvgSelector"] = "SvgSelector"
    value: str  # raw <svg>...</svg>


class TextQuoteSelector(BaseModel):
    type: Literal["TextQuoteSelector"] = "TextQuoteSelector"
    exact: str
    prefix: Optional[str] = None
    suffix: Optional[str] = None


Selector = Union[FragmentSelector, SvgSelector, TextQuoteSelector]


class Target(BaseModel):
    source: str
    selector: List[Selector] = Field(default_factory=list)


class SpecificResourceBody(BaseModel):
    type: Literal["SpecificResource"] = "SpecificResource"
    purpose: Literal["classifying", "tagging", "describing", "linking"] = "classifying"
    source: str  # e.g. "regnskap-no:Eiendeler"


class TextualBody(BaseModel):
    type: Literal["TextualBody"] = "TextualBody"
    purpose: Literal["tagging", "commenting", "describing"] = "tagging"
    value: str
    format: str = "text/plain"
    language: Optional[str] = None


Body = Union[SpecificResourceBody, TextualBody]


class Creator(BaseModel):
    id: str
    type: Literal["Software", "Person", "Organization"] = "Software"
    name: Optional[str] = None
    homepage: Optional[str] = None


class CascadeConfidence(BaseModel):
    voters: int
    of: int
    text: Optional[str] = None
    voters_hit: Optional[List[str]] = None
    column_dropped_voters: Optional[List[str]] = None


class Annotation(BaseModel):
    """A WADM-conformant annotation extended with regnskapsnoter namespaced fields."""

    id: str
    type: Literal["Annotation"] = "Annotation"
    motivation: Literal["tagging", "classifying", "linking", "identifying"] = "tagging"
    created: str
    creator: Creator
    target: Target
    body: List[Body]

    # Namespaced extensions (round-trip safely through ``model_dump`` because we
    # alias them to keys with colons via ``populate_by_name`` + a custom dumper).
    cascade_confidence: Optional[CascadeConfidence] = Field(
        default=None,
        alias="registrum:cascadeConfidence",
    )
    period_type: Optional[Literal["instant", "duration"]] = Field(
        default=None, alias="registrum:periodType",
    )
    balance: Optional[Literal["debit", "credit"]] = Field(
        default=None, alias="registrum:balance",
    )
    period_start: Optional[str] = Field(default=None, alias="registrum:periodStart")
    period_end: Optional[str] = Field(default=None, alias="registrum:periodEnd")
    dimensions: Optional[Dict[str, str]] = Field(
        default=None, alias="registrum:dimensions",
    )
    schema_versions: Optional[Dict[str, str]] = Field(
        default=None, alias="registrum:schemaVersions",
    )

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}


# ---- Builder ----------------------------------------------------------

def make_annotation_id() -> str:
    return f"urn:regnskapsnoter:annotation:{uuid4().hex}"


def make_pdf_target(
    *,
    pdf_uri: str,
    page_no: int,
    bbox: Optional[tuple] = None,
    consensus_text: Optional[str] = None,
    text_prefix: Optional[str] = None,
    text_suffix: Optional[str] = None,
) -> Target:
    """Build a WADM Target for a PDF page region.

    Includes:
    - FragmentSelector with ``page=N`` (Media Fragments URI)
    - SvgSelector with a single rect at the bbox (in page coordinates)
    - TextQuoteSelector with the consensus text + optional prefix/suffix context
    """
    selectors: List[Selector] = [
        FragmentSelector(value=f"page={page_no}"),
    ]
    if bbox is not None:
        l, t, r, b = bbox
        svg = (
            f"<svg xmlns='http://www.w3.org/2000/svg'>"
            f"<rect x='{l:g}' y='{t:g}' width='{r - l:g}' height='{b - t:g}'/>"
            f"</svg>"
        )
        selectors.append(SvgSelector(value=svg))
    if consensus_text:
        selectors.append(TextQuoteSelector(
            exact=consensus_text, prefix=text_prefix, suffix=text_suffix,
        ))
    return Target(source=pdf_uri, selector=selectors)


def build_fact_annotation(
    *,
    pdf_uri: str,
    page_no: int,
    bbox: tuple,
    concept_id: str,
    value_text: str,
    consensus_text: Optional[str] = None,
    cascade_voters_hit: Optional[List[str]] = None,
    cascade_voters_total: Optional[int] = None,
    column_dropped_voters: Optional[List[str]] = None,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    dimensions: Optional[Dict[str, str]] = None,
    schema_versions: Optional[Dict[str, str]] = None,
    creator_id: str = "urn:regnskapsnoter:pipeline:dev",
    creator_homepage: str = "https://github.com/sondreskarsten/regnskapsnoter",
    language: str = "no",
) -> Annotation:
    """High-level builder: produces a typed Annotation for a single fact."""
    target = make_pdf_target(
        pdf_uri=pdf_uri, page_no=page_no, bbox=bbox,
        consensus_text=consensus_text or value_text,
    )
    body: List[Body] = [
        SpecificResourceBody(purpose="classifying", source=concept_id),
        TextualBody(purpose="tagging", value=value_text, language=language),
    ]

    # Pull period_type/balance from the taxonomy if available
    period_type = None
    balance = None
    concept = get_concept(concept_id)
    if concept is not None:
        period_type = concept.period_type
        balance = concept.balance

    cascade = None
    if cascade_voters_hit is not None and cascade_voters_total is not None:
        n_hit = len(cascade_voters_hit)
        cascade = CascadeConfidence(
            voters=n_hit,
            of=cascade_voters_total,
            text="unanimous" if n_hit == cascade_voters_total else f"{n_hit}/{cascade_voters_total}",
            voters_hit=cascade_voters_hit,
            column_dropped_voters=column_dropped_voters,
        )

    return Annotation(
        id=make_annotation_id(),
        motivation="tagging",
        created=dt.datetime.now(dt.timezone.utc).isoformat(),
        creator=Creator(id=creator_id, homepage=creator_homepage),
        target=target,
        body=body,
        cascade_confidence=cascade,
        period_type=period_type,
        balance=balance,
        period_start=period_start,
        period_end=period_end,
        dimensions=dimensions,
        schema_versions=schema_versions,
    )


# ---- Serialisation ----------------------------------------------------

def annotation_to_jsonld(ann: Annotation) -> Dict[str, Any]:
    """Serialise a single annotation to JSON-LD with the WADM @context."""
    data = ann.model_dump(by_alias=True, exclude_none=True)
    return {
        "@context": [
            WADM_CONTEXT,
            {"regnskap-no": "https://github.com/sondreskarsten/regnskapnoter-taxonomy/concepts/"},
        ],
        **data,
    }


def annotations_to_jsonld_collection(
    anns: List[Annotation], *, label: str = "Regnskapsnoter facts"
) -> Dict[str, Any]:
    """Serialise multiple annotations as a WADM AnnotationCollection."""
    return {
        "@context": [
            WADM_CONTEXT,
            {"regnskap-no": "https://github.com/sondreskarsten/regnskapnoter-taxonomy/concepts/"},
        ],
        "id": f"urn:regnskapsnoter:collection:{uuid4().hex}",
        "type": "AnnotationCollection",
        "label": label,
        "total": len(anns),
        "first": {
            "id": f"urn:regnskapsnoter:page:{uuid4().hex}",
            "type": "AnnotationPage",
            "items": [ann.model_dump(by_alias=True, exclude_none=True) for ann in anns],
        },
    }


def write_jsonl(anns: List[Annotation], path: str) -> int:
    """Write one annotation per line as JSON-LD (each with its own @context).

    Returns the number of annotations written.
    """
    n = 0
    with open(path, "w") as f:
        for ann in anns:
            f.write(json.dumps(annotation_to_jsonld(ann), ensure_ascii=False))
            f.write("\n")
            n += 1
    return n
