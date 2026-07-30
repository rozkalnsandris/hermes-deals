# Lidl Review Queue

Hermes Deals uses a precision-first Lidl ingestion policy.

## Quality target

- Aim for at least ~90% automatic extraction of the relevant physical-store flyer scope.
- 90% is a coverage target, not permission to publish incorrect rows.
- High-confidence rows may proceed to normal promotion.
- Ambiguous rows go to the Review Queue.
- Parser tuning can continue over future flyers without blocking the whole project.

## Data separation

The parser observation is immutable. Human review is an overlay:

`original_payload + corrected_payload -> effective reviewed payload`

Manual edits never overwrite `original_payload`.

`offer_review_revisions` is an append-only audit history for seed, draft, follow-up, approve, reject and reopen actions.

## Approval and persistence

`save_offer_candidates()` enforces an exact immutable offer-set per snapshot. A manually approved single offer is therefore not appended to the original flyer snapshot.

Approval creates a deterministic derived `SourceSnapshot` with `strategy_hint=manual_review_v1`, then persists exactly one reviewed offer through the normal `save_offer_candidates()` path.

The Review Queue retains the original source snapshot ID, flyer key, page, parser version, source hashes/geometry/crop references, original payload and manual corrections.

## UI

Review page:

`/ui/review`

Available actions:

- Save correction
- Needs follow-up
- Approve & Publish
- Reject
- Return to pending

Approved rows cannot be reopened automatically because that would require an explicit unpublish workflow.

## Crop support

The Review UI displays `provenance.crop_url` when present. For weekly page alerts and products created from their hints, the dedicated Lidl worker pre-renders SHA256-bound page and context PNG assets from the immutable flyer PDF. The API remains PyMuPDF-free and only serves validated files from the fixed Review preview asset root; it never accepts an arbitrary filesystem path and never changes Review or offer state.


## Weekly page-review alerts

The weekly Lidl completeness stop-rule does not reconstruct every missing
product automatically.

A `page_alert` is stored in the existing Review Queue as a non-publishable
review item. It contains only reviewed page provenance plus strict native title
hints. Product price/package truth is intentionally absent.

The Review UI renders page alerts separately:

- each hint can create an idempotent normal product Review row;
- product name and flyer validity are prefilled;
- price/package remain manual;
- the generated product row follows the ordinary correction + approval path;
- a page alert itself can never be approved/published as an offer;
- after human inspection the alert can be marked checked (stored using the
  existing rejected/closed state and audit revision).

Before seeding weekly artifacts, the bridge compares candidates and hints with
existing Review history on the same flyer/page. Only strong same-product
matches are suppressed, so uncertain aliases remain visible for manual review.
