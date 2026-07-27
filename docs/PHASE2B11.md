# Phase 2B11 — Lidl deterministic unit-price consistency audit

Goal: add an independent arithmetic check before any Lidl offer can move toward persistence.

## What changes

- Keep the Phase 2B10 dual-PSM (11 + 12) OCR and semantic product pairing gates.
- For automatic OCR candidates, inspect nearby OCR lines classified as unit prices.
- Parse package amounts such as `800 g`, `190 g`, `400 g`, `500 ml`.
- Convert the package amount to kg/l and calculate `unit price × package quantity`.
- Compare the calculated amount with the OCR sale price using a conservative rounding tolerance.
- Record verified math evidence, missing evidence, and strong arithmetic conflicts separately.

Examples expected from the measured sample:

- `Hackfleisch`: 800 g × 11.86 €/kg ≈ 9.49 €.
- `Pesto`: 190 g × 5.21 €/kg ≈ 0.99 €.
- `Tomaten`: 400 g × 1.48 €/kg ≈ 0.59 €.

## Safety

- No Lidl database writes.
- Netto collector/API unchanged.
- Playwright remains unused.
- Existing raw snapshots are preserved.

## Decision gate

If several automatic candidates receive independent unit-price arithmetic verification with zero strong conflicts, the next phase may scale the dry-run candidate builder to all grocery-relevant flyer pages.
