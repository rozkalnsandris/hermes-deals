# Phase 3B — revised product identity schema

Phase 3B implements ADR 0001 without normalizing or linking any production offers.

Four additive tables are introduced:

1. `offer_normalizations` — versioned interpretation of immutable retailer observations.
2. `canonical_products` — exact purchasable trade-item/package identities.
3. `product_match_candidates` — many reviewable candidates per normalized offer.
4. `offer_product_links` — final confirmed offer-to-product identity only.

Important database invariants:

- normalization is unique per `(offer_candidate_id, normalizer_version)`;
- a match candidate cannot reference a normalization belonging to another offer;
- multiple canonical candidates may coexist for one offer;
- candidate uniqueness is scoped to `(offer_normalization_id, canonical_product_id, matcher_version)`;
- candidate confidence is `0..1`;
- `pending` candidates have no `decided_at`; accepted/rejected candidates require it;
- one offer may have at most one final confirmed link;
- when a final link references a match candidate, the candidate must belong to the same offer and canonical product;
- `CanonicalProduct.gtin14` is unique when present;
- Phase 3B performs zero normalization, zero canonical creation, zero candidate generation and zero link backfill.

GTIN checksum validation remains application/normalizer responsibility; the database stores the canonical 14-digit representation and enforces structural length.
