# Lidl parallel campaign source inspection — source-only processing contract (#906)

## Why this is not a flyer selection

Selected store `DE06664` advertises two concurrently valid official campaign identities for 2026-11-23..28: `aktionsprospekt-23-11-2026-28-11-2026-36518f` (`/ar/10`) and `aktionsprospekt-23-11-2026-28-11-2026-cde58d` (`/ar/21`). The store hub and inspected Schwarz API metadata do not supply a verified weekly-grocery priority. The merged [multi-campaign classification](LIDL_MULTI_CAMPAIGN_CLASSIFICATION_CONTRACT.md) and [independent review](LIDL_PARALLEL_CAMPAIGN_REVIEW_DESIGN.md) therefore remain **advisory only**.

**Owner-approved source-only next stage:** independently inspect *already captured* source JSON/PDF bytes per candidate, verify identities and content hashes, and return provenance-bound, non-writing review records. This is a real in-memory verification/conditioning operation, **not** an implemented collector, product parser, import, or live resolver.

## Implementation / inputs

`backend/app/lidl_independent_campaign_processing.py` defines `inspect_independent_campaign_sources(ambiguity, store_external_id, berlin_as_of, source_evidence, observations=None)`.

- `ambiguity` is the complete, **BLOCKED** `LidlFamilyAmbiguityError.review`; it is validated by the existing review planner from PR #1201. Store `DE06664`, Berlin as-of date, candidate identities and validity intervals are validated there. A truncated, injected, duplicate or partial ambiguity is rejected.
- `source_evidence` is a mapping keyed by the **(flyer identifier, route region)** pair; values are existing `FlyerEvidence` records from a separately authorized source capture. The routine itself performs no network, disk, host, API, DB, corpus or publication writes. Unlisted extra keys are rejected; missing expected keys produce explicit `MISSING_SOURCE_SNAPSHOT` lanes.
- Each record must match its *own* validated candidate target, flyer identifier, route region and dates; recorded raw JSON and PDF sizes and SHA-256 digests must match the exact supplied bytes. A genuine `%PDF` header and bounded byte sizes are required. This checks input consistency, not authenticity of upstream collection.
- Raw JSON is UTF-8 with no duplicate keys; the existing `_validate_flyer_payload()` enforces API offer dates and advertised route-region membership. The official flyer UUID, full advertised region list, PDF URL, page count, official Lidl viewer URL/host, final viewer host, and referenced PDF HTTPS URL must match the associated `FlyerEvidence`. The inspected API must have a canonical official flyer UUID.
- The deterministic per-campaign `source_provenance` includes selected store identity, target, flyer identity and route, validity, official UUID, advertised region list, raw/PDF SHA-256 and byte counts, page count, hashes of source URLs, and a SHA-256 over canonical provenance fields. `origin_attested=false` explicitly signals that matching supplied bytes **does not** prove first-party origin.

## Independent failure isolation and immutable output semantics

Each candidate produces a bounded review lane with one of `VERIFIED_INPUT_SNAPSHOT`, `MISSING_SOURCE_SNAPSHOT` or `REJECTED_INPUT_SNAPSHOT`. Invalid candidate evidence supplies a stable rejection reason and **no trusted provenance**. Another candidate's valid snapshot is not used as fallback, nor promoted to winner. Source map order and hub link order cannot select a flyer. A third simultaneous flyer is preserved, not silently discarded. The report contains **no raw PDF/JSON bytes, product rows, URLs, source-fetch instructions or write hooks**.

Even if `source_inputs_complete=true` for every independently verified snapshot, the **parent is always** `planning_scope=SOURCE_ONLY_OFFLINE`, `gate_a_result=BLOCKED`, `decision=UNRESOLVED`, `review_required=true`, `selection_authorized=false`, `collection_authorized=false`, `gate_b_authorized=false`, `corpus_write_authorized=false`, `db_write_authorized=false`, `publication_authorized=false`, `runtime_registration_authorized=false`, `write_performed=false`. The preexisting review-only per-lane `classification_authorized=false` and `collection_authorized=false` are unchanged. Human `GROCERY_LIKE` impressions are never authority.

## What is deliberately not implemented or authorized

This PR only adds one pure Python module, one regression test file and this document. Existing selected-store discovery, Gate A runner/sanitizer/dispatch, parser graph, immutable corpus, offer DB, Review queue, publication, scheduled jobs and RPi5 runtime are **untouched**. A validated in-memory source is **not** a WAIT_SOURCE receipt, Gate B input, campaign identity classification, production candidate, or automatic independent collection.

A later stage would require trusted **first-party store/date/campaign applicability evidence** or another explicit owner-approved resolution/independent publication policy; a separate reviewed source PR to capture original sources with authenticated provenance, campaign-specific immutable namespaces and product duplicate/conflict semantics; exact CI, independent MERGE authorization, then separately scoped exact-LIVE authorizations before executing or writing anything. The currently observed [Gate A run 44917379495](https://github.com/rozkalnsandris/hermes-deals/actions/runs/44917379495) is still `BLOCKED`, exit 30, not WAIT_SOURCE.

## Regression tests

`backend/tests/test_lidl_independent_campaign_processing.py` covers the exact two 2026-11 flyer identities, deterministic order, missing/tampered/swapped snapshot isolation, SHA mismatch, API region/validity/PDF/UUID/page-count mismatch, unsafe URLs and bytes, duplicate JSON keys, injected source/observation authority, unexpected/truncated identities and three simultaneous candidates. Parent and lane authorization flags must remain false in all scenarios. Full repository CI is source evidence only, not proof of live Lidl freshness.
