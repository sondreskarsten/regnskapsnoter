# regnskapsnoter-xbrl

Emit Inline XBRL (iXBRL 1.1) from regnskap-no facts.

Closes audit C6: walks a list of resolved facts (each carrying a
`regnskap-no:*` concept ID, value, period_end) and produces an
XHTML+iXBRL document validatable by Arelle.

## Usage

```python
from regnskapsnoter_xbrl import IxbrlFact, build_ixbrl

facts = [
    IxbrlFact(
        concept_id="regnskap-no:Eiendeler",
        value=300_000,
        period_end="2024-12-31",
    ),
    IxbrlFact(
        concept_id="regnskap-no:Anleggsmidler",
        value=100_000,
        period_end="2024-12-31",
    ),
    IxbrlFact(
        concept_id="regnskap-no:Omlopsmidler",
        value=200_000,
        period_end="2024-12-31",
    ),
]

xhtml_bytes = build_ixbrl(
    facts,
    entity_orgnr="811602892",
    period_start="2024-01-01",
    period_end="2024-12-31",
    currency="NOK",
)

with open("aarsregnskap_2024.xhtml", "wb") as f:
    f.write(xhtml_bytes)
```

## What's emitted

- Single XHTML document with the `xhtml`, `ix`, `xbrli`, `iso4217`,
  `link`, `xlink`, and `regnskap-no` namespaces declared on the root.
- One `<xbrli:context>` per (period_type, period) combination.
  Balance items become `<xbrli:instant>` contexts; P&L items become
  `<xbrli:startDate>`/`<xbrli:endDate>` duration contexts.
- One `<xbrli:unit>` per unit (NOK/shares/pure).
- Each fact emitted as `<ix:nonFraction>` (numeric) or
  `<ix:nonNumeric>` (text) with `name`, `contextRef`, `unitRef`,
  `decimals`, optional `sign` attributes.

## Period type inference

`period_type` and `unit` are read from the regnskap-no taxonomy via
`api.get_concept(concept_id)`. Override per fact by setting
`IxbrlFact.period_type` and `IxbrlFact.unit` if the inference is wrong
or the taxonomy lacks the concept.

## License

MIT
