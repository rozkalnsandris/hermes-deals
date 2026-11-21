# Lidl multi-campaign classification contract — review only (#906)

## Decision boundary

The selected Lidl store `DE06664` (Husener Straße 44, Dortmund) can publish two distinct official flyers for the same validity period. On `2026-11-21`, `target=next`, both `2026-11-23..2026-11-28` candidates are valid:

| Flyer suffix | Flyer route | Content observation (not authority) |
| --- | --- | --- |
| `36518f` | `/ar/10` | Black Weeks, primarily nonfood |
| `cde58d` | `/ar/21` | Food and drinks |

The official store page lists both as *Aktionsprospekt*. The Schwarz `/v4/flyer` fields for both are `name=Aktionsprospekt`, `category=Filial-Angebote`, `subcategory=Unsere Aktionsprospekte`, `isRecommended=true`, `status=current`, and `offerStartDate=2026-11-23` / `offerEndDate=2026-11-28`. Their advertised region lists overlap, including region `7` for both. No authoritative program-level discriminator was found in the inspected structured fields. The existing live discovery therefore **must keep failing closed** with `LidlFamilyAmbiguityError`, `BLOCKED` / exit `30` and no selected flyer.

## Review-only source contract

`backend/app/lidl_multi_campaign_review.py` converts an **existing**, bounded `LidlFamilyAmbiguityError.review` into a deterministic source-level human-review draft with:

- `kind=lidl_multi_campaign_classification_review`, schema `1`; selected store, Berlin as-of, target and every distinct flyer/route/validity identity;
- immutable authority indicators: `gate_a_result=BLOCKED`, `decision=UNRESOLVED`, `review_required=true`, `selection_authorized=false`, `classification_status=AUTHORITATIVE_RULE_NOT_ESTABLISHED`;
- no PDF, raw API response, cookie, viewer URL, token, product payload, human approval, selected flyer or write capability.

The draft rejects extra/unexpected keys, invalid store/date, candidate/slug date mismatch, duplicates, incomplete or truncated candidate sets, and any source review that suggests selection authority. The review covers *all* competing current candidates or the shared nearest-next start; it does not infer a program from `/ar/`, cover text, page count or ordering.

`annotate_human_observations()` accepts only identity-bound, **advisory** human impressions with `proposed_program=UNDETERMINED|GROCERY_LIKE|OTHER_CAMPAIGN_LIKE` and `basis=NONE|CONTENT_HINT_ONLY|UNVERIFIED_API_FIELD`. These are labels for manual discussion, **not** source facts or permissions. Even a complete set of opposing proposed labels remains `BLOCKED`, `UNRESOLVED`, `selection_authorized=false`. Unknown/missing observation is not a safe implicit selection. The function cannot accept `approved`, `selected_flyer`, arbitrary URLs or an `authoritative` flag.

This is a **source-only contract**. It is intentionally **not wired** to the runtime Gate A sanitizer/dispatcher, not a new Gate B input, not a database schema and not a way to run a collection. The existing sanitized `multi_candidate_review` remains unchanged.

## Human review and future design gate

1. Review **every** official selected-store candidate and preserve immutable flyer identifier, per-flyer region, validity, official store identity and the reviewed observation provenance. Treat a content/marketing label as a hypothesis only.
2. To establish a program classification, separately verify a stable **first-party structured campaign/applicability** signal, its documented interpretation, exact store/date applicability and whether concurrent campaigns may both legitimately apply. A mere reviewer guess or model classification does not supply that signal.
3. If a first-party distinction cannot be established, keep the result `BLOCKED` and request an explicit owner design decision for multi-campaign handling. Do not default to groceries, region `21`, the shortest/longest flyer, or the first/last link.
4. Any future authorized resolver needs a separate scope/PR with source-backed eligibility rules, complete conflicting-candidate fixtures, missing/equal/conflicting authority tests, reviewer authorization semantics, independent MERGE and exact-SHA LIVE gates. This document **does not** approve any resolution rule.

## Regression and evidence

`backend/tests/test_lidl_multi_campaign_review.py` uses the exact two November 2026 flyer identities, reverse-order stability, manual impressions with no upgrade, missing/partial reviews, malformed/truncated/duplicate records, current-period ambiguity and unsafe authority injections. The original `backend/tests/test_lidl_family_source_discovery.py` and Gate A sanitization regression remain authoritative for live `BLOCKED` semantics.

Runtime evidence: [Gate A run 44917379495](https://github.com/rozkalnsandris/hermes-deals/actions/runs/44917379495) (PR #1198 merge SHA `82f4f8a8d965d853a4b1a2da11e01dae87d95999`, artifact `14712615031`, exit `30`). Not a `WAIT_SOURCE` receipt. No corpus freeze, DB/Review write, publication, systemd change, deployment, runtime retry or Gate B authorization follows from this contract.
