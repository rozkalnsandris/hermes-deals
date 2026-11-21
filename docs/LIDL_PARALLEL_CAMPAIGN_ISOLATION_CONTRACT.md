# Lidl #906 — independent campaign isolation and conflict quarantine

## Owner-approved architecture (source design only)

The owner approved independent multi-campaign processing with isolated identities, source provenance and conflict quarantine. This is a **review-only source design**, not authorization for automatic flyer selection, product identity inference, deduplication, data import, Gate A/B dispatch, immutable corpus writes, DB/Review writes, publication, deploy or RPi5 mutation.

For selected store DE06664, the owner-authorized 2026-11-21 one-shot first-party capture (main d81975d5fb47968466548b45c0ab5d10c87c376c) validated both 2026-11-23..28 campaigns in memory:

| Identity | Route | Official flyer UUID | Pages | PDF SHA-256 |
|---|---|---|---|---|
| 36518f | ar/10 | 01a1f337-d071-79c3-88f6-fd78bb726819 | 43 | 36c3cd122ed9562b574cf7e42eba8cbc0ca97b66f35801334d4babcaeb252ddd |
| cde58d | ar/21 | 01a1f3f4-232f-7c2c-8048-6602a231b978 | 36 | b2db1270ea74fe5f73c4a195b2b436af55ec5342c4e046c6f38cdfad07ef5df6 |

The observed source validity, regions and hashes were confirmed in memory, **not saved** in a corpus or database. Both campaigns advertised region 7 and region 21. This is overlapping API metadata, **not** an authoritative store-to-program applicability rule or evidence that individual products are equal. The earlier Gate A failure remains BLOCKED / exit 30, not WAIT_SOURCE.

## Pure, testable contract

Module: `backend/app/lidl_parallel_campaign_isolation.py`.

`plan_parallel_campaign_isolation(ambiguity, store_external_id, berlin_as_of, source_evidence)` accepts a complete BLOCKED ambiguity plus each candidate's independently acquired `FlyerEvidence` (raw JSON/PDF bytes held by the caller). It delegates full validation to `inspect_independent_campaign_sources`: campaign identity, canonical dates, selected-store binding, official flyer UUID, advertised route region, API metadata, PDF header, raw/PDF lengths and SHA-256, and URL properties. Unsupported/truncated/extra/injected candidates are rejected by the existing strict validators.

Each independently validated snapshot receives a source-revision-specific `campaign_namespace_sha256` binding store, target, flyer slug and route, date range, official UUID and verified provenance SHA-256. These digests are **logical identity only**: no directories, tables, offer IDs or publisher namespaces are created. Missing or invalid snapshots are quarantined without a trusted namespace; another candidate can never replace them.

For **already verified** campaign pairs, the pure routine produces review-only `conflict_quarantine` records if:

- the official API advertised region sets overlap within overlapping validity dates;
- the official flyer UUID is reused across distinct campaign identities;
- the exact PDF SHA-256 is reused across distinct campaign identities.

Each matching pair quarantines **both** source lanes; all relevant reasons are retained. Source order does not imply priority. Shared regions or PDF bytes do not establish equal products. There is no candidate parsing, price comparison, automatic product linking, product identity inference or deduplication. Without a detected pairwise conflict, a validated lane remains `AWAITING_PROGRAM_APPLICABILITY`, **not approved**. A source missing/invalid lane stays `QUARANTINED`.

The output contains only selected-store and candidate identity metadata, hashed source provenance, advisory conflict codes, shared region codes and validity intervals. No raw PDF/JSON, source URLs, product mappings, prices, offers, credentials or network access. All outputs explicitly preserve `gate_a_result=BLOCKED`, `decision=UNRESOLVED`, `review_required=true`, `origin_attested=false`, and every selection/classification/collection/deduplication/production/write authorization as false. Hash matching is integrity checking, **not cryptographic proof of origin**.

## Acceptance and next authority gates

`backend/tests/test_lidl_parallel_campaign_isolation.py` exercises the two-campaign overlap, deterministic order, incomplete and tampered snapshots, unrelated regions, official UUID and PDF content collisions, source revision changes, three-campaign pairs, swapped inputs, injected authority and invalid extra/truncated identities. Tests are synthetic fixtures; do not confuse them with live Lidl product or program evidence.

The source-only PR must pass required exact-head CI/reviews, then requires a separate owner MERGE. A subsequent data-processing stage still needs separately reviewed provenance-bound product-level parsing, explicit campaign applicability rules, review procedures for real offer duplicates/conflicts, and independent LIVE authorities for any on-host capture, Gate A/B integration, immutable retention, production DB/Review or publication. The present module cannot produce any of those effects.
