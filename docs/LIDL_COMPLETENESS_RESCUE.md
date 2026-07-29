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
- `scope`
- `channel=physical_store`
- `confidence`
- `review_required=true`
- `production_ready=false`

`candidate_key` is the stable Review identity. Evidence changes for an already
seeded key therefore fail closed through the existing immutable Review seed
contract instead of silently creating a replacement.
