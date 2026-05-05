# regnskap-no

The Norwegian regnskap noter taxonomy as a Python wheel.

This package ships the build artifacts of
[`regnskapnoter-taxonomy`](https://github.com/sondreskarsten/regnskapnoter-taxonomy)
v1.0.3 — 279 concepts, 4 dimensional axes (31 members), 97 calc arcs, 302
mappings, 290 references — and exposes typed lookup helpers, SHACL validation,
and Pydantic-schema generators for typed extraction.

## Standards stack

- **XBRL 2.1** information model (concept attributes, calc arcs, dimensional hypercubes)
- **SKOS** for vocabulary semantics (prefLabel, altLabel, broader/narrower, mappings)
- **WADM** as the binding layer for fact annotation
- **SHACL + JSON Schema** for validation
- **SemVer 2.0.0** — concept IDs are forever; deprecation never reuses

Authority sources: regnskapsloven §§ 6-1, 6-1a, 6-2, 7-35 to 7-46 + NRS standards.

## Install

```bash
pip install regnskap-no                    # core only
pip install regnskap-no[shacl]             # + rdflib + pyshacl
pip install regnskap-no[fuzzy]             # + rapidfuzz for canonicalizer
pip install regnskap-no[embed]             # + sentence-transformers
```

## Usage

```python
from regnskap_no import api

# Concept lookup
c = api.get_concept("regnskap-no:SumEiendeler")
print(c.period_type, c.balance, c.standard_label("nb"))

# Search by Norwegian label
for m in api.search_label("Sum eiendeler", lang="nb"):
    print(m.subject_id, m.role, m.text)

# Calc-arc children
arcs = api.get_calc_children("regnskap-no:SumEiendeler",
                              role="resultatregnskap-etter-art")
for a in arcs:
    print(a.child_id, a.weight)

# IFRS-Full and norwegian_specific mappings
for m in api.get_mappings("regnskap-no:SumEiendeler"):
    print(m.relation, m.target)

# regnskapsloven references
for r in api.get_references("regnskap-no:SumEiendeler"):
    print(r.publisher, r.document, r.paragraph)
```

## Pydantic schema generation

```python
from regnskap_no.prompts import (
    pydantic_for_calc_arc,
    pydantic_for_axis_dict,
    pydantic_for_hypercube,
)

# 1-D model: parent + child fields
SumEiendelerModel = pydantic_for_calc_arc(
    "regnskap-no:SumEiendeler",
    role="balanse-eiendeler",
)

# Egenkapital movement: 5 components × 5 events
EgenkapitalRollforward = pydantic_for_hypercube(
    primary_concepts=["regnskap-no:Egenkapital"],
    row_axis="regnskap-no:EgenkapitalKomponentAxis",
    col_axis="regnskap-no:EgenkapitalEndringAxis",
)
```

## SHACL validation

```python
from regnskap_no.shacl import validate_taxonomy, validate_facts

# Sanity check (always passes for a published wheel)
ok, report = validate_taxonomy()
assert ok

# Validate extracted facts
ok, report = validate_facts(my_rdf_graph)
```

## License

CC-BY-4.0 (taxonomy + this wheel). Source-of-truth repo:
https://github.com/sondreskarsten/regnskapnoter-taxonomy
