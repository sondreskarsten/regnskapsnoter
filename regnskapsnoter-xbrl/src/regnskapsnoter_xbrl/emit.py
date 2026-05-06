"""iXBRL emitter.

Generates an Inline XBRL 1.1 document from a list of facts. Each fact
becomes either ``<ix:nonFraction>`` (numeric) or ``<ix:nonNumeric>``
(text), wrapped in a minimal XHTML body. Context + unit references are
declared once in ``<ix:header>``.

Schema reference: regnskap-no concepts use the ``regnskap-no`` namespace
prefix bound to ``https://taxonomy.regnskap.no/v1`` (matches the SKOS
graph the wheel ships).

Numeric formatting follows the Norwegian convention (thin-space thousands
separator) but emits the raw machine-readable integer in the
``ix:nonFraction`` element. Negative values use the sign attribute
(``sign="-"``) per the iXBRL spec.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

from lxml import etree


# Namespaces used in the output document
NS = {
    "xhtml": "http://www.w3.org/1999/xhtml",
    "ix": "http://www.xbrl.org/2013/inlineXBRL",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "regnskap-no": "https://taxonomy.regnskap.no/v1",
}


@dataclass
class IxbrlFact:
    """One fact ready for iXBRL emission.

    Attributes:
        concept_id: prefixed concept ID (e.g. ``regnskap-no:Eiendeler``).
        value: numeric value (int or float) for monetary/numeric facts;
            string for textual facts.
        period_end: ISO period-end (``YYYY-MM-DD``). Determines the
            context. For instant concepts (balance items), this is the
            instant date. For duration concepts (P&L items), the period
            spans ``period_start`` (passed to ``build_ixbrl``) to
            ``period_end``.
        decimals: precision attribute (xbrli:decimals). 0 = whole NOK,
            -3 = thousands NOK. Default 0.
        unit: 'NOK', 'shares', 'pure'. If None, inferred from concept's
            data_type.
        period_type: 'instant' or 'duration'. If None, inferred from
            taxonomy.
    """

    concept_id: str
    value: object
    period_end: str
    decimals: int = 0
    unit: Optional[str] = None
    period_type: Optional[str] = None


def _qname(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def _split_concept(concept_id: str) -> tuple[str, str]:
    """Split a prefixed concept ID into (prefix, local) parts."""
    if ":" not in concept_id:
        raise ValueError(f"concept_id missing prefix: {concept_id}")
    prefix, local = concept_id.split(":", 1)
    return prefix, local


def _infer_period_type(concept_id: str) -> str:
    """Look up period_type from regnskap-no taxonomy if available."""
    try:
        from regnskap_no import api
        c = api.get_concept(concept_id)
        if c is not None and c.period_type:
            return c.period_type
    except Exception:
        pass
    # Default to duration (P&L is more common in extracted facts than balance)
    return "duration"


def _infer_unit(concept_id: str, default: str = "NOK") -> str:
    try:
        from regnskap_no import api
        c = api.get_concept(concept_id)
        if c is not None and c.data_type:
            dt = c.data_type.lower()
            if "monetary" in dt:
                return default
            if "shares" in dt:
                return "shares"
            if "decimal" in dt or "pure" in dt or "percent" in dt:
                return "pure"
    except Exception:
        pass
    return default


def _make_context_id(period_type: str, period_start: str, period_end: str) -> str:
    if period_type == "instant":
        return f"ctx_instant_{period_end}".replace("-", "")
    return f"ctx_duration_{period_start}_{period_end}".replace("-", "")


def _make_unit_id(unit: str) -> str:
    return f"unit_{unit.lower()}"


def _format_negative(v: int) -> tuple[str, str]:
    """Return (numeric_text, sign_attr) for a possibly-negative number."""
    if isinstance(v, (int, float)) and v < 0:
        return (str(abs(int(v))), "-")
    return (str(int(v)) if isinstance(v, (int, float)) else str(v), "")


def build_ixbrl(
    facts: Iterable[IxbrlFact],
    *,
    entity_orgnr: str,
    period_start: str,
    period_end: str,
    currency: str = "NOK",
    schema_ref: str = "https://taxonomy.regnskap.no/v1/regnskap-no.xsd",
) -> bytes:
    """Build an iXBRL XHTML document from a list of facts.

    Args:
        facts: list of IxbrlFact.
        entity_orgnr: 9-digit Norwegian organisation number for the
            xbrli:entity/xbrli:identifier element.
        period_start: ISO start date for duration contexts.
        period_end: ISO end date (used for instant contexts and as the
            period end for durations).
        currency: ISO 4217 code; bound to ``iso4217:NOK`` etc. by default.
        schema_ref: href for the schema reference. Default points at the
            regnskap-no namespace URI; replace if you publish a hosted
            .xsd.

    Returns:
        UTF-8 encoded bytes of the resulting XHTML document.
    """
    fact_list = list(facts)

    # Discover all (period_type, period) and (unit) combinations
    contexts: dict[str, dict] = {}
    units: dict[str, str] = {}

    for f in fact_list:
        ptype = f.period_type or _infer_period_type(f.concept_id)
        ctx_id = _make_context_id(ptype, period_start, f.period_end)
        if ctx_id not in contexts:
            contexts[ctx_id] = {
                "id": ctx_id,
                "period_type": ptype,
                "period_start": period_start,
                "period_end": f.period_end,
            }
        unit_name = f.unit or _infer_unit(f.concept_id, currency)
        unit_id = _make_unit_id(unit_name)
        units[unit_id] = unit_name
        f._resolved_ctx = ctx_id  # type: ignore[attr-defined]
        f._resolved_unit = unit_id  # type: ignore[attr-defined]
        f._resolved_unit_name = unit_name  # type: ignore[attr-defined]
        f._resolved_period_type = ptype  # type: ignore[attr-defined]

    # Build document
    nsmap = {
        None: NS["xhtml"],
        "ix": NS["ix"],
        "xbrli": NS["xbrli"],
        "iso4217": NS["iso4217"],
        "link": NS["link"],
        "xlink": NS["xlink"],
        "regnskap-no": NS["regnskap-no"],
    }
    html = etree.Element(_qname("xhtml", "html"), nsmap=nsmap)
    head = etree.SubElement(html, _qname("xhtml", "head"))
    title = etree.SubElement(head, _qname("xhtml", "title"))
    title.text = f"Regnskapsnoter iXBRL — {entity_orgnr} — {period_end}"

    body = etree.SubElement(html, _qname("xhtml", "body"))

    # ix:header (contexts + units + schema ref)
    header = etree.SubElement(body, _qname("ix", "header"))
    references = etree.SubElement(header, _qname("ix", "references"))
    schema_link = etree.SubElement(references, _qname("link", "schemaRef"))
    schema_link.set(_qname("xlink", "type"), "simple")
    schema_link.set(_qname("xlink", "href"), schema_ref)

    resources = etree.SubElement(header, _qname("ix", "resources"))

    # Contexts
    for ctx in contexts.values():
        ctx_el = etree.SubElement(
            resources, _qname("xbrli", "context"), id=ctx["id"],
        )
        entity = etree.SubElement(ctx_el, _qname("xbrli", "entity"))
        ident = etree.SubElement(entity, _qname("xbrli", "identifier"),
                                  scheme="https://www.brreg.no/")
        ident.text = entity_orgnr
        period = etree.SubElement(ctx_el, _qname("xbrli", "period"))
        if ctx["period_type"] == "instant":
            inst = etree.SubElement(period, _qname("xbrli", "instant"))
            inst.text = ctx["period_end"]
        else:
            sd = etree.SubElement(period, _qname("xbrli", "startDate"))
            sd.text = ctx["period_start"]
            ed = etree.SubElement(period, _qname("xbrli", "endDate"))
            ed.text = ctx["period_end"]

    # Units
    for unit_id, unit_name in units.items():
        unit_el = etree.SubElement(resources, _qname("xbrli", "unit"),
                                    id=unit_id)
        measure = etree.SubElement(unit_el, _qname("xbrli", "measure"))
        if unit_name == "NOK":
            measure.text = f"iso4217:{unit_name}"
        else:
            measure.text = f"xbrli:{unit_name}"

    # Facts in a div
    div = etree.SubElement(body, _qname("xhtml", "div"))
    h1 = etree.SubElement(div, _qname("xhtml", "h1"))
    h1.text = f"Regnskap {period_end}"

    for f in fact_list:
        prefix, local = _split_concept(f.concept_id)
        is_text = isinstance(f.value, str) and not _is_numeric_string(f.value)

        p = etree.SubElement(div, _qname("xhtml", "p"))
        if is_text:
            tag = etree.SubElement(
                p, _qname("ix", "nonNumeric"),
                attrib={
                    "name": f.concept_id,
                    "contextRef": f._resolved_ctx,  # type: ignore[attr-defined]
                },
            )
            tag.text = str(f.value)
        else:
            value_text, sign_attr = _format_negative(f.value)
            attribs = {
                "name": f.concept_id,
                "contextRef": f._resolved_ctx,  # type: ignore[attr-defined]
                "unitRef": f._resolved_unit,    # type: ignore[attr-defined]
                "decimals": str(f.decimals),
            }
            if sign_attr:
                attribs["sign"] = sign_attr
            tag = etree.SubElement(p, _qname("ix", "nonFraction"), attrib=attribs)
            tag.text = value_text

    return etree.tostring(
        html, xml_declaration=True, encoding="utf-8",
        standalone=False, pretty_print=True,
    )


_NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _is_numeric_string(s: str) -> bool:
    return bool(_NUMERIC_RE.match(s.strip()))
