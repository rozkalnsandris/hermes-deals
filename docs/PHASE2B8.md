# Phase 2B8 — Lidl OCR precision filtering + product-label pairing audit

Phase 2B7 fixed the Tesseract TSV parser and proved that Lidl flyer images contain usable OCR geometry. The RPi5 audit also showed that the first geometry gate was still too permissive:

- shipping (`Versandkostenpauschale 5,95`) could remain a sale candidate;
- installment amounts near `Ratenzahlung / pro Monat` could remain sale candidates;
- package quantities such as `0,75` could look like prices;
- `000` could be emitted as a zero-value price;
- substring grocery matching classified unrelated pages as grocery pages (`reis` inside `Preis`, etc.).

Phase 2B8 keeps Lidl DB writes disabled and improves precision before any persistence:

1. grocery terms are matched as OCR word tokens, not arbitrary substrings;
2. price classification uses both the price line and nearby OCR context;
3. shipping, delivery, installment, unit/reference and package amounts are excluded;
4. zero-value price tokens are rejected;
5. low-emphasis line-text numbers require stronger visual evidence;
6. each remaining credible price zone receives ranked nearby product-label candidates using OCR bounding-box geometry;
7. the result is an audit report only — no Lidl offers are written to PostgreSQL yet.

A future persistence phase is allowed only after real RPi5 output shows that the remaining credible zones are substantially cleaner and product-label pairing is useful on actual grocery pages.
