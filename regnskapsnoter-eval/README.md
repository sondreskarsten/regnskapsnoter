# regnskapsnoter-eval

The v2-fixture eval harness — port of `ocr-cascade-eval`'s scoring methodology
into the Regnskapsnoter monorepo so the empirical claim "99/100 reliable"
is reproducible from this repo's CI.

## Scoring

A truth value `n` is recovered by an engine iff
[`number_present(n, engine_text)`](src/regnskapsnoter_eval/scoring.py)
finds it. Matches:

- Grouped Norwegian thousands (`12 345 678` with any whitespace between groups)
- Digit-by-digit (`12345678`, also tolerating whitespace between digits)
- Sign: ASCII minus, Unicode minus (`U+2212`), or surrounding parentheses

A truth value is *reliable* when ≥ `min_voters_for_reliable` voters' output
text contains it. The production threshold is 7 (matches the
`ocr-cascade-eval` v2 audit result).

## Truth source

`gs://sondre_brreg_data/raw/ocr_eval_v2_10pdfs_300dpi/audit/brreg_ground_truth/{orgnr}.json`,
mirrored locally under `tests/data/brreg_ground_truth/` for CI.

## Public API

```python
from regnskapsnoter_eval import (
    load_truth_from_local, truth_numbers,
    score_per_voter, score_consensus, score_fixture, number_present,
)

truth = load_truth_from_local("tests/data/brreg_ground_truth/")
nums = truth_numbers(truth)

# After running the cascade against each fixture PDF:
fs = score_fixture(
    cells_per_orgnr_per_voter=cells,   # {orgnr: {voter: list[TextCell]}}
    truth_per_orgnr=nums,               # {orgnr: set[int]}
    min_voters_for_reliable=7,
)
print(f"unanimous: {fs.n_unanimous}/{fs.n_truth_values}")
print(f"reliable: {fs.n_reliable}/{fs.n_truth_values}")
print(f"universal-miss: {fs.n_universal_miss}/{fs.n_truth_values}")
```

## License

MIT
