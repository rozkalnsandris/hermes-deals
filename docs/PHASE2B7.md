# Phase 2B7 — Lidl OCR TSV hardening + price geometry audit

Phase 2B6 proved that Tesseract is fast enough on the RPi5 and can read useful text from Lidl flyer page images. It also exposed two quality problems that must be fixed before any Lidl database writes:

1. Tesseract TSV is tab-separated, not CSV-quoted. The previous `csv.DictReader` parser could treat a literal OCR double quote as the start of a quoted field and swallow many physical TSV rows. This produced impossible output such as 24 words but >22k text characters and hundreds of fake prices originating from TSV coordinates/confidence values.
2. A naive price regex classified non-prices such as `9-teilig` and unit/reference/shipping prices as offer-price candidates.

Phase 2B7 therefore keeps DB writes disabled and re-runs the same targeted sample with:

- a physical-row TSV parser with no quote semantics;
- conservative textual price extraction;
- classification of unit, shipping, installment and reference prices;
- large-euro + smaller-cent geometry pairing for Lidl's visual price layout;
- bounding boxes, height ratios and nearby text for each candidate;
- a sanity gate on malformed TSV rows.

The next phase is allowed to persist Lidl offers only after this audit shows a useful number of credible sale-price zones and the product-name pairing strategy can be validated.
