"""regnskapsnoter-wadm — W3C Web Annotation Data Model emitter for regnskap facts."""
from .wadm import (
    Annotation,
    Body,
    CascadeConfidence,
    Creator,
    FragmentSelector,
    SpecificResourceBody,
    SvgSelector,
    Target,
    TextQuoteSelector,
    TextualBody,
    annotation_to_jsonld,
    annotations_to_jsonld_collection,
    build_fact_annotation,
    make_annotation_id,
    make_pdf_target,
    write_jsonl,
)

__version__ = "0.1.0"

__all__ = [
    "Annotation",
    "Body",
    "CascadeConfidence",
    "Creator",
    "FragmentSelector",
    "SpecificResourceBody",
    "SvgSelector",
    "Target",
    "TextQuoteSelector",
    "TextualBody",
    "annotation_to_jsonld",
    "annotations_to_jsonld_collection",
    "build_fact_annotation",
    "make_annotation_id",
    "make_pdf_target",
    "write_jsonl",
]
