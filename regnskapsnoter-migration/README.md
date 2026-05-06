# regnskapsnoter-migration

Shadow-mode runner + per-concept drift dashboards for migrating the
18,924-PDF noter corpus from the v1 extraction (Gemini PDF prompt) to v2
(cascade + canonicaliser + SHACL).

Closes audit C11.

## Usage

```python
from regnskapsnoter_migration import (
    Fact, diff_facts, per_concept_drift,
    per_orgnr_summary, write_diff_parquet,
)

v1 = [
    Fact("811602892", "regnskap-no:Eiendeler", 300_000, "2024-12-31", "v1"),
    Fact("811602892", "regnskap-no:Anleggsmidler", 100_000, "2024-12-31", "v1"),
]
v2 = [
    Fact("811602892", "regnskap-no:Eiendeler", 300_000, "2024-12-31", "v2"),
    Fact("811602892", "regnskap-no:Anleggsmidler", 105_000, "2024-12-31", "v2"),
]

entries = diff_facts(v1, v2)
# [DiffEntry(kind='disagree', abs_delta=5000, rel_delta=0.05, ...),
#  DiffEntry(kind='agree', abs_delta=0, ...)]

concept_report = per_concept_drift(entries)
print(concept_report.agreement_rate("regnskap-no:Eiendeler"))   # 1.0
print(concept_report.agreement_rate("regnskap-no:Anleggsmidler"))  # 0.0

write_diff_parquet(entries, "gs://sondre_brreg_data/migration/v1_v2_diff.parquet")
```

## Diff kinds

A fact is identified by `(orgnr, concept_id, period_end)`. The same key
either appears in v1, v2, or both. The diff produces one `DiffEntry` per
unique key, classified by `kind`:

- `agree`: v1 and v2 produced the same integer value (rounded)
- `disagree`: both produced a value but they differ
- `v1_only`: v1 had it, v2 dropped it
- `v2_only`: v2 added it, v1 had no fact for this key

Numerical equality uses `int(round(value))` — no fuzzy tolerance. Apply
tolerance downstream from the `abs_delta` / `rel_delta` columns.

## Reports

`per_concept_drift(entries)` and `per_orgnr_summary(entries)` aggregate
DiffEntries into a `DriftReport`:

```python
report.rows["regnskap-no:Eiendeler"]
# {"n_agree": 2, "n_disagree": 0, "n_v1_only": 0, "n_v2_only": 0}

report.agreement_rate("regnskap-no:Eiendeler")
# 1.0   (n_agree / (n_agree + n_disagree); None if no comparable facts)

report.to_records()
# [{"key": "regnskap-no:Eiendeler", "n_agree": 2, ..., "agreement_rate": 1.0}, ...]
```

## Parquet output

`write_diff_parquet(entries, path)` writes a flat parquet with these
columns (all strings + nullable doubles):

- `orgnr`, `concept_id`, `period_end`, `kind`
- `v1_value`, `v2_value` (nullable)
- `abs_delta`, `rel_delta` (nullable; inf when v1 was 0)

## License

MIT
