# Phase 2B12 — Lidl unit-price conflict resolution audit

Goal: resolve the single arithmetic conflict found in Phase 2B11 before scaling OCR to all grocery pages.

## What changes

- Keep the dual-PSM (11 + 12), semantic pairing, and deterministic unit-price math gates.
- Read package sizes from the same OCR line as the unit price, e.g. `Je 190 g; 1kg = 5.21`.
- Explicitly ignore canonical unit-price bases such as `1kg = ...` when selecting the product package size.
- Preserve math conflicts instead of overwriting OCR sale prices.
- Mark a conflict as a **correction candidate** only when:
  - the unit-price relation is close to the sale price zone,
  - the product label overlaps semantically with the unit-price context,
  - unit-price × package-size yields the expected price,
  - and the OCR sale price differs from that expected price by exactly one digit with the same whole-euro part.

Example from the measured sample:

- OCR: `Penne Rigate 0.59`.
- Unit price: `1.38 €/kg`.
- Package: `500 g`.
- Arithmetic: `0.5 × 1.38 = 0.69`.
- Result: keep `0.59` as raw OCR evidence and emit `0.69` only as an audit correction proposal.

## Safety

- No Lidl database writes.
- No price is silently changed.
- Netto collector/API remains unchanged.
- Playwright remains unused.
- Existing raw snapshots are preserved.

## Decision gate

If the same 8-page sample yields at least four math-verified automatic candidates and no unresolved arithmetic conflicts, the next phase may scale a dry-run candidate builder to all grocery-relevant Lidl flyer pages.
