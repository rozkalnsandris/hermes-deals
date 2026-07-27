# ADR 0001 — Product identity, matching and price history

Status: Implemented by Alembic 0003_product_identity

## Context

Phase 3A/3Aa established that `offer_candidates` are already immutable price observations and that broad automatic fuzzy linking is not justified by current data.

The first proposed Phase 3B model combined pending/rejected match candidates and final confirmed links in one table with a unique `offer_candidate_id`. That cannot preserve several competing candidates and rejection history for one offer observation.

## Decision

Use four separate concepts.

### OfferNormalization

Versioned interpretation of one immutable `OfferCandidate`.

Planned fields: `id`, `offer_candidate_id`, `normalizer_version`, `normalized_name`, `normalized_brand`, `item_quantity_value`, `item_quantity_unit`, `pack_count`, nullable `gtin14`, nullable `category_key`, `evidence_json`, `created_at`.

Uniqueness: `(offer_candidate_id, normalizer_version)`.

GTIN is normalized to a 14-digit internal representation only after validating an explicit GTIN/EAN/UPC/barcode source value with the GS1 check digit. Original value/path remains evidence.

### CanonicalProduct

Specific purchasable trade-item/package identity.

Planned fields: `id`, `display_name`, `normalized_name`, `brand_display`, `brand_normalized`, `item_quantity_value`, `item_quantity_unit`, `pack_count`, nullable unique `gtin14`, nullable `category_key`, `created_at`, `updated_at`.

### ProductMatchCandidate

Many candidate rows may exist for one offer observation.

Planned fields: `id`, `offer_candidate_id`, `offer_normalization_id`, `canonical_product_id`, `matcher_version`, `match_method`, `confidence`, `evidence_json`, `review_status` (`pending`, `accepted`, `rejected`), `decision_reason`, `created_at`, `decided_at`.

Implemented candidate uniqueness: `(offer_normalization_id, canonical_product_id, matcher_version)`, allowing each normalizer version to retain its own auditable candidate set.

Rejected candidates are retained. Fuzzy candidates are review-only.

### OfferProductLink

Final confirmed identity only.

Planned fields: `id`, unique `offer_candidate_id`, `canonical_product_id`, nullable `source_match_candidate_id`, `link_method`, `confidence`, `linked_at`, and later `linked_by_member_id` after household auth exists.

This table contains no pending/rejected workflow state.

## Matching hierarchy

1. explicit valid GTIN exact — strongest candidate;
2. exact normalized brand + name + compatible exact package;
3. exact normalized brand + name when package evidence is absent on both sides;
4. exact name with incomplete evidence — review;
5. `pg_trgm` / fuzzy similarity — review only.

Package conflict or conflicting explicit GTIN is a hard negative signal. No score alone creates a confirmed link during initial Phase 3.

## Shopping concepts

`CanonicalProduct` is not household intent. A later `ProductGroup`/shopping-concept layer represents substitutable needs such as “milk” or “tomatoes”. Free-text list items do not require canonical products.

## Price history

Do not create a duplicate `price_history` table initially. Derive history from `CanonicalProduct <- OfferProductLink -> OfferCandidate`.

## Identifier audit snapshot

```json
{
  "aldi_nord": {
    "persisted_raw": {
      "retailer_id_hits": 867
    },
    "snapshot_json": {
      "snapshot_files_scanned": 5,
      "snapshot_non_json": 5
    },
    "valid_gtin_total": 0
  },
  "edeka": {
    "persisted_raw": {},
    "snapshot_json": {
      "snapshot_files_scanned": 4,
      "snapshot_non_json": 4
    },
    "valid_gtin_total": 0
  },
  "lidl": {
    "persisted_raw": {},
    "snapshot_json": {
      "retailer_id_hits": 284,
      "snapshot_files_scanned": 4,
      "snapshot_non_json": 3
    },
    "valid_gtin_total": 0
  },
  "netto": {
    "persisted_raw": {},
    "snapshot_json": {
      "snapshot_files_scanned": 6,
      "snapshot_non_json": 6
    },
    "valid_gtin_total": 0
  }
}
```

Retailer chains with at least one explicit valid-GTIN-key value in this run: `none`.

These counts are audit evidence, not a permanent source contract.

## Consequences

- the older two-table Phase 3B migration is superseded;
- normalization is versioned and auditable;
- one offer may retain multiple candidate/rejection records;
- final confirmed identity is separate;
- price history remains provenance-preserving;
- a later shopping-concept layer can be added cleanly.
