# Lidl completeness rescue

This layer handles genuine false-negative cards that were not emitted by the
frozen / provenance-bound Lidl parser corpus.

It is deliberately additive.

## Safety contract

A completeness rescue record:

- is bound to an exact flyer key, scan name, raw SHA256, PDF SHA256, parser
  version and parser SHA256;
- is bound to one page and one evidence bbox;
- must identify evidence as either `native_geometry` or `targeted_ocr`;
- must set `review_required=true`;
- may never set `production_ready=true`;
- is seeded only into the existing Review queue;
- can only become an OfferCandidate through the existing manual Review
  approval flow.

Historical parser rows are never rewritten.

## Evidence order

1. Native PDF geometry (`words` / `dict`) first.
2. Targeted OCR only for a bounded card/page region when native text is absent
   or unusable.
3. Review.
4. Existing immutable manual publication path.

## Artifact

The importer consumes JSONL. Every row contains:

- `schema_version`
- `candidate_key`
- exact source/parser identity
- `page`
- `evidence_kind`
- `bbox`
- `evidence_text`
- `product_name`
- optional package / price fields
- `requires_app` (mandatory `true` whenever `app_price_eur` is present)
- `scope`
- `channel=physical_store`
- `confidence`
- `review_required=true`
- `production_ready=false`

`candidate_key` is the stable Review identity. Evidence changes for an already
seeded key therefore fail closed through the existing immutable Review seed
contract instead of silently creating a replacement.

## Read-layer precedence for reviewed rescue publications

Stable `source_offer_id` remains the primary observation identity. A manually
approved completeness-rescue publication may represent the same physical flyer
deal as an already-persisted parser observation under a different
`source_offer_id`. The family Current/Upcoming read path therefore applies one
additional, narrow precedence rule after stable-identity deduplication:

- only an immutable `completeness_rescue_review` publication can trigger it;
- source chain, store, normalized product name, base price, validity window and
  source URL must all match exactly;
- the reviewed rescue publication wins the read view;
- neither historical observation is deleted or updated.

This prevents a reviewed enrichment from appearing as a second family deal
without weakening persistence identity or generic retailer deduplication.

## Lidl weekly completeness stop-rule

R6.1 is the precision parser. Hermes Deals does not require 100% automatic
booklet reconstruction.

The weekly workflow has two safe outcomes:

1. a clear native Lidl display-price anchor that is not owned by the
   authoritative scan can create a Review candidate;
2. remaining plausible unrepresented strict titles on a reviewed physical
   target page create a page-level Review alert with title/bbox hints.

A page alert is deliberately not a second product parser. It does not invent a
sale price, package, validity, or product truth. The final few percent are
completed manually in Review.

The agreed target is approximately 90% automatic precision/coverage plus safe
Review handling. OCR is optional diagnostic/enrichment only and is not a release
gate for completeness. Do not block Hermes Deals progress trying to force 100%
automatic Lidl reconstruction.

`review-profile.json` remains the authoritative page-role gate when present.
The workflow remains non-writing until an explicit later Review integration
step: no database writes, no automatic Review seeding, and no auto-publication.


## Review UI bridge

`app.lidl_weekly_review_bridge` is the bridge between weekly shadow artifacts
and the existing human Review model.

It preserves the stop-rule:

- native unowned-price candidates may become normal Review product rows;
- page alerts remain non-product Review rows;
- page-alert hints are manual prefill only;
- already-reviewed strong same-product matches suppress duplicate weekly
  candidates/hints;
- source snapshot resolution is provenance-bound to the exact Lidl raw SHA and
  excludes derived `manual_review_v1` snapshots;
- no page alert can be published directly.
