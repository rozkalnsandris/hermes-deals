# Phase 2B17 — Lidl OfferCandidate contract shadow mapping

Phase 2B17 consumes the latest Phase 2B16 Lidl candidate-precision audit and maps **only** `strict_ready` rows into the existing Phase-1 `OfferCandidate` Pydantic contract.

This is still a non-writing shadow stage:

- no Lidl fetch;
- no OCR;
- no PostgreSQL insert/update/delete;
- no correction-review price is silently substituted;
- every mapped entry is emitted with `db_write_eligible=false` in its shadow provenance;
- a deterministic synthetic snapshot UUID is used only to exercise the current contract before real Lidl source-snapshot persistence exists.

The mapping validates:

- `source_chain=lidl`;
- deterministic source offer IDs;
- flyer validity dates;
- exact OCR sale price for strict-ready rows;
- package/unit-price fields where available;
- exact flyer API source URL;
- page-image provenance from the full-grocery OCR report;
- current `OfferCandidate` schema validation.

A successful report recommendation is `lidl_offer_candidate_shadow_contract_valid`. The next persistence step must replace the synthetic shadow snapshot with a real immutable Lidl source snapshot before any database write is enabled.
