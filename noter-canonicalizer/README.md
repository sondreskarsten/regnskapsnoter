# noter-canonicalizer

Resolve observed Norwegian noter labels to `regnskap-no:*` concept IDs.

## Cascade

1. **Exact** match (NFKC + casefold + whitespace + bokmål/nynorsk equivalence)
2. **Fuzzy** (rapidfuzz token-set ratio ≥ 0.95)
3. **Embedding** (`NbAiLab/nb-sbert-base` cosine ≥ 0.78)

## Usage

```python
from noter_canonicalizer import resolve, resolve_many

r = resolve("Eiendeler")
print(r.match.concept_id, r.match.confidence, r.match.method)
# regnskap-no:Eiendeler 1.0 exact

# With fuzzy and embedding stages enabled
r = resolve("Eiendeler totalt", use_fuzzy=True, use_embedding=True)
```

Below threshold → unresolved; the `candidates` list contains the top-K nearest
matches so a human review queue can suggest a new altLabel back to the taxonomy.

## License

MIT
