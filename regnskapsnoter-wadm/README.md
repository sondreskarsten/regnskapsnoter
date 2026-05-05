# regnskapsnoter-wadm

W3C Web Annotation Data Model emitter for regnskap fact extractions.

Each emitted annotation links:
- A PDF page region (FragmentSelector + SvgSelector)
- The cascade-consensus text (TextQuoteSelector)
- A `regnskap-no:*` concept ID (purpose=`classifying`)
- A typed value (purpose=`tagging`)
- Cascade vote diagnostics (`registrum:cascadeConfidence` extension)
- XBRL period/balance attributes

## License

MIT
