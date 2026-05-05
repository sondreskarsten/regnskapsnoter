# regnskapsnoter-shacl

SHACL + Python-side validator for regnskap fact extractions.

Two layers of validation:

1. **SHACL graph validation** against the bundled taxonomy shapes (delegates to
   `regnskap-no.shacl`).
2. **Python-side fact consistency**:
   - Calc-arc summation: every `regnskap-no:Sum*` parent's value must equal the
     sum of its calc-arc children within tolerance.
   - Period type consistency: `instant` concepts must carry a `periodEnd`;
     `duration` concepts must carry both `periodStart` and `periodEnd`.
   - Balance polarity: `debit` concepts may not be negative-by-convention
     (parenthesised), and vice versa for `credit` concepts.
   - Dimensional consistency: facts in a hypercube must reference valid axis
     members of the declared axis.

Quarantines the failing facts; passes the rest.

## License

MIT
