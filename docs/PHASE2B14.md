# Hermes Deals Phase 2B14 — Lidl full-grocery dry run

Phase 2B14 scales the already-audited Lidl OCR pipeline from the 8-page sample to every flyer page that Lidl metadata identifies as grocery-related.

Safety rules:
- no Lidl database writes;
- no silent OCR price correction;
- PSM 11 + 12 remain the only OCR modes;
- unit-price math corrections remain review proposals;
- every dry-run candidate is emitted with `db_write_eligible=false`;
- current Netto data remains a regression gate.

The dry-run report separates candidates into `math_verified`, `math_correction_review`, `semantic_price_only`, and `unresolved_math_conflict` tiers. The purpose is to measure real whole-flyer coverage before mapping Lidl candidates into the OfferCandidate contract.
