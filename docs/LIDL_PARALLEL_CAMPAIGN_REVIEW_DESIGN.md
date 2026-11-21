# Lidl independent concurrent-campaign review design (#906)

## Scope and non-selection contract

The selected Lidl store `DE06664` (Husener Straße 44, Dortmund) exposes two distinct official flyers valid November 23–28, 2026: `36518f/ar/10` (Black Weeks / nonfood-like) and `cde58d/ar/21` (food-like). The selected-store page and inspected Schwarz `/v4/flyer` fields do not establish a uniquely authoritative weekly-grocery priority rule. These are concurrent campaigns to be reviewed independently, never an ordered list from which a winner is automatically selected.

**Mandatory invariants:** Keep parent Gate A `BLOCKED` (exit 30), `decision=UNRESOLVED`, `review_required=true`, `selection_authorized=false`. Neither one completed review nor two opposing reviewer impressions may authorize a specific flyer, source collection, Gate B, corpus writes or production publication.

This design complements [the merged source-only classification contract](LIDL_MULTI_CAMPAIGN_CLASSIFICATION_CONTRACT.md) from PR #1200 and preserves its fail-closed validation and source-of-truth constraints. It does not modify any live runner or dispatch path.

## Source-only independent lanes

`backend/app/lidl_independent_campaign_review.py` exposes the pure `plan_independent_campaign_reviews(ambiguity, store_external_id, berlin_as_of, observations=None)` function. It takes an existing `LidlFamilyAmbiguityError.review` payload and delegates strict validation to `prepare_multi_campaign_review()` and `annotate_human_observations()`.

Each candidate becomes exactly one review lane keyed by the parent store, target, flyer identifier, per-flyer route region and validity window. Lanes contain:

- `flyer_identifier`, `route_region`, `valid_from`, `valid_until` copied from validated candidate identities;
- `review_state=AWAITING_HUMAN_REVIEW|ADVISORY_OBSERVATION_RECORDED`;
- `proposed_program=UNDETERMINED|GROCERY_LIKE|OTHER_CAMPAIGN_LIKE` and `observation_basis=NONE|CONTENT_HINT_ONLY|UNVERIFIED_API_FIELD`;
- `classification_authorized=false` and `collection_authorized=false`.

The parent plan carries `planning_scope=SOURCE_ONLY_ADVISORY`, `gate_a_result=BLOCKED`, `decision=UNRESOLVED`, `review_required=true`, `selection_authorized=false`, `collection_authorized=false`, `gate_b_authorized=false`, `corpus_write_authorized=false`, and `production_publish_authorized=false`.

**No implied ranking:** The candidate order is deterministic only for audit/diff stability. It is not eligibility, precedence, first-choice, canonical grocery selection or a reason to discard any concurrent candidate. No priority, selected flyer, source URL, PDF, token, cookie, API request or processing instruction is emitted.

**Review isolation:** An annotation for one candidate changes only that lane. Missing or conflicting notes remain unresolved. Three or more concurrent candidates remain separate up to the existing limit of 12; truncated, duplicate, injected, incomplete or otherwise invalid input is rejected rather than silently reduced to a subset.

## Provenance and trust boundary

1. The validated candidate identity is supplied by the selected-store hub ambiguity and is not independently revalidated by this pure review planner. Route-region numbers do not prove the selected Lidl store or a campaign program.
2. Official labels, cover text, `isRecommended`, overlapping regions, marketing parameters, PDF suffixes and page counts are non-authoritative classification hints. Human labels are advisory, not owner authorization or signed first-party applicability evidence.
3. No networking, local filesystem mutation, DB/corpus/Review write, collection, runner change, workflow dispatch, Gate A decision change, publication or deploy occurs in this design. Existing live Gate A and Gate B code paths are deliberately unchanged.
4. A future independently authorized processing design needs a first-party store/date/program applicability contract, immutable per-campaign provenance (official flyer UUID, route, dates, raw/PDF hashes), campaign-specific freeze namespaces, conflicting/duplicate campaign rules and isolation of failures. None of these are implemented or authorized here.
5. A future resolver or ingestion integration needs its own scoped change, regressions for missing/ambiguous/conflicting authority, CI, explicit merge and separate exact-SHA LIVE authorizations. Until then neither campaign can advance via this review-only plan.

## Regression coverage

`backend/tests/test_lidl_independent_campaign_review.py` covers the real 2026-11-23..28 pair, deterministic reversed-order stability, isolated partial human review, full advisory annotation with no promotion, a third concurrent candidate, truncated/duplicate/poisoned candidate rejection, human authority injection rejection, and a current-period ambiguity. The original `test_lidl_multi_campaign_review.py` and `test_lidl_family_source_discovery.py` continue to enforce the source-level and Gate A ambiguity contracts.

Successful GitHub CI proves repository-level behavior only, never host registration or production correctness.

## Existing external evidence

[Owner-dispatched Lidl Gate A run 44917379495](https://github.com/rozkalnsandris/hermes-deals/actions/runs/44917379495) returned `BLOCKED` / exit `30` with two selected-store candidates and sanitized artifact `14712615031`, not a `WAIT_SOURCE` receipt. This source-only design does not create a Gate B corpus-freeze prerequisite or any LIVE authority.
