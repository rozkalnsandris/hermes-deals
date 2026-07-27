# Hermes Deals — Phase 2B13

Phase 2B13 tightens the final audit gate before a full Lidl grocery dry-run.

The previous Phase 2B12 arithmetic correctly found a real `0.59` vs `0.69`
unit-price conflict but did not mark it as correctable because correction logic
required the unit-price OCR box to be within 260 px of the sale price. Dense Lidl
cards can place the product/unit-price line farther away.

This phase keeps correction proposals conservative. A wider (<=650 px) geometry
window is accepted only when all of the following are true:

- the sale price is an already-approved automatic semantic candidate;
- PSM 11 and PSM 12 both support the sale-price zone;
- the unit-price context has semantic overlap with the paired product label;
- package-size × unit-price arithmetic conflicts with the OCR sale price;
- actual and expected prices have the same whole-euro part and differ in exactly
  one digit in their two-decimal representations.

A correction remains audit metadata only. No Lidl offer is persisted and no OCR
price is silently mutated.
