# Phase 2B10 — Lidl dual-PSM precision + semantic product pairing

Goal: turn the Phase 2B9 OCR ensemble into a conservative pre-persistence audit.

## What changes

- Drop PSM 6 from the candidate ensemble. In the measured Phase 2B9 sample it added two low-confidence, package/unit-like candidates while tripling OCR work. The audit now uses PSM 11 + 12.
- Preserve the full Lidl `keyWords` and `altText` strings in the page-schema report so OCR labels can be checked against retailer-provided metadata instead of geometry alone.
- Re-rank OCR product labels with semantic evidence from Lidl metadata.
- Reject obvious non-product labels: URLs, origin/footer text, package-only labels, dimensions and generic category-only labels.
- Mark an `automatic_candidate` only when all three are true:
  1. the page is grocery-relevant,
  2. the price has multi-PSM support or very strong split-price geometry,
  3. the product label has semantic evidence from Lidl metadata.

## Safety

- No Lidl database writes.
- Netto collector and API remain unchanged.
- Playwright remains unused.
- Existing raw snapshots are preserved.

## Decision gate

The report distinguishes:

- raw/credible OCR prices,
- semantic product pairings,
- automatic pre-persistence candidates.

If automatic candidates remain sparse, the next step is targeted region OCR/image preprocessing rather than weakening confidence gates.
