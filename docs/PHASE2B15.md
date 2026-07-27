# Phase 2B15 — Lidl full-grocery candidate precision audit

Phase 2B14 proved that the full metadata-selected Lidl grocery set can be OCRed reliably (37/37 pages), but its 69 dry-run candidates still contain obvious label noise. Phase 2B15 deliberately does **not** rerun OCR and does **not** write any database rows.

It post-processes the latest `*-lidl-ocr-full-grocery-dry-run.json` and measures product-label precision before the core pairing rules are changed.

The audit:

- keeps mathematically verified candidates as the strongest evidence tier;
- keeps math correction candidates review-only;
- cleans trivial dangling OCR glue such as `COCA-COLA in` -> `COCA-COLA`;
- rejects obvious package/promotion strings, dangling fragments, origin-only labels and descriptor-only labels;
- scores semantic-only rows using PSM support, Lidl metadata overlap, grocery terms and brand-like labels;
- never sets `db_write_eligible=true`;
- saves a separate `*-lidl-candidate-precision-audit.json` report.

This phase is intentionally a cheap post-processing audit. Its output decides which precision rules should be moved into the core Lidl collector before the next full OCR run.
