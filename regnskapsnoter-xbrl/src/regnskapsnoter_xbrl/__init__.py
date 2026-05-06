"""regnskapsnoter-xbrl — emit Inline XBRL from regnskap-no facts.

Audit C6 closed: produces a self-contained XHTML+iXBRL document where
each fact is wrapped in ``<ix:nonFraction>`` (numeric) or ``<ix:nonNumeric>``
(text), and the report contexts/units are declared in the
``<ix:header>`` block.

Public API:

    from regnskapsnoter_xbrl import IxbrlFact, build_ixbrl

    facts = [
        IxbrlFact(
            concept_id="regnskap-no:Eiendeler",
            value=300_000,
            period_end="2024-12-31",
            decimals=0,
        ),
    ]
    xhtml_bytes = build_ixbrl(
        facts,
        entity_orgnr="811602892",
        period_start="2024-01-01",
        period_end="2024-12-31",
        currency="NOK",
    )

The output is a UTF-8 encoded XHTML document. Inline XBRL inside.
Validates with Arelle (iXBRL 1.1 spec).
"""
from __future__ import annotations

from .emit import IxbrlFact, build_ixbrl

__version__ = "0.1.0"

__all__ = ["IxbrlFact", "build_ixbrl"]
