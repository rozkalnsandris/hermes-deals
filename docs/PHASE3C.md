# Phase 3C — normalizer-v1 read-only intelligence gate

Phase 3C adds a pure, deterministic normalization module and evaluates it against the real production `OfferCandidate` dataset without writing any Phase 3 identity rows.

Rules:

- `OfferCandidate` remains immutable source truth.
- normalization is deterministic and versioned as `normalizer-v1`;
- names/brands are Unicode-normalized and case-folded without dropping meaningful numeric identity;
- package parsing is conservative and only recognizes explicit metric/piece patterns;
- kg/l/cl/mg are converted to base g/ml representations while preserving pack count;
- GTIN is accepted only from explicit GTIN/EAN/UPC/barcode keys and only with a valid checksum;
- retailer-local IDs and digit-looking image filenames never become GTIN;
- package conflict is a hard negative for exact identity;
- fuzzy text similarity generates review evidence only.

Because `canonical_products` is intentionally empty after Phase 3B, this phase does not write `product_match_candidates`. Instead it creates a JSON review report of unique normalized retailer identity nodes and cross-store candidate pairs. A later controlled phase will create canonical products only from reviewed evidence.
