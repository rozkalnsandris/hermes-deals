# Phase 2B18 — Lidl immutable source provenance binding

Phase 2B18 closes the provenance gap exposed by the Phase 2B17 OfferCandidate shadow mapping.

The current-week Lidl public flyer JSON that originally fed the page-schema/OCR chain is now copied into a content-addressed canonical raw path and registered as a real `SourceSnapshot` row. The original API-fetch SHA256 and byte count must match the raw payload before registration.

The registration is idempotent by `(source_chain=lidl, sha256)` and never mutates an existing immutable snapshot. Re-running the binding therefore reuses the same `SourceSnapshot` instead of creating duplicate source rows.

The already validated strict-ready OfferCandidate shadow objects are then revalidated with this real persisted `snapshot_id`. This remains a shadow mapping: no Lidl `offer_candidates` rows are written in this phase.

Safety gates:

- exact current flyer JSON SHA256 must match the original Lidl API fetch metadata;
- canonical snapshot path is content-addressed by SHA256;
- raw flyer validity dates must match the OCR dry-run provenance;
- all mapped OfferCandidates must reference the real persisted SourceSnapshot;
- all mapped rows remain `db_write_eligible=false`;
- Lidl offer row count must remain unchanged;
- repeated provenance binding must be idempotent.

Successful recommendation: `lidl_real_snapshot_offer_shadow_valid`.
