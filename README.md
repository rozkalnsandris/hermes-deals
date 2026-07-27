# Hermes Deals

Private, fully custom family shopping-intelligence platform for Andris' household.

## Current status — Phase 3B

The retailer persistence foundation is complete across Netto, Lidl, ALDI Nord and the family-primary EDEKA Patzer store. Hermes Deals is now entering the product-identity layer: versioned normalization, evidence-backed match candidates, confirmed canonical-product links and derived price history.

Current Lidl evidence chain:

`public flyer JSON -> immutable SourceSnapshot -> page metadata -> dual-PSM OCR -> semantic pairing -> unit-price math -> strict persistence gate -> OfferCandidate -> controlled DB persistence`

Lidl persistence remains intentionally conservative at five production offers. Four are `math_verified`; Penne Rigate is the first controlled `math_corrected_verified` offer, with original OCR name/price and dual-PSM recovery evidence retained. Unreviewed correction/semantic-only candidates remain outside persistence.

### Implemented foundation

- PostgreSQL 18 + SQLAlchemy 2 + Psycopg 3 + Alembic
- FastAPI + Pydantic `OfferCandidate` contract
- immutable raw retailer snapshots and provenance reports
- Netto parser and persisted family-primary offers
- ALDI Nord structured collector and persisted offers
- EDEKA Patzer store-aware collector and persisted offers
- Lidl public flyer API discovery and content-addressed canonical snapshot
- Lidl OCR precision, semantic pairing, unit-price arithmetic and strict persistence gates
- Nginx single-origin `/`, `/api`, `/ws` layout
- Docker Compose on Raspberry Pi 5
- regression/unit tests and guarded deployment/rollback scripts

### Safety rules

- raw retailer evidence is immutable;
- PostgreSQL is the source of truth;
- a retailer parser cannot bypass `OfferCandidate` validation;
- Lidl review/correction candidates are never silently promoted; only explicitly audited corrected evidence may pass a controlled persistence gate;
- the first controlled Lidl write refuses unexpected existing rows;
- deterministic IDs make the approved write set repeatable;
- DB-level `(snapshot_id, source_offer_id)` uniqueness and PostgreSQL conflict-safe inserts are deployed; concurrency, rollback atomicity and idempotent replay have been validated on real PostgreSQL.

See `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/CODE_REVIEW_2026-07-24.md`.

### Phase 3 product-identity direction

`OfferCandidate` remains an immutable retailer price observation. Phase 3 adds a separate, versioned identity layer:

`OfferCandidate -> OfferNormalization -> ProductMatchCandidate -> confirmed OfferProductLink -> CanonicalProduct`

Multiple match candidates and rejected decisions must remain auditable; a final confirmed link is stored separately. GTIN is the strongest exact trade-item identifier when explicit source evidence and a valid check digit are available. Retailer-local SKU/article/product IDs remain source-local evidence. Text similarity and PostgreSQL `pg_trgm` are candidate-generation tools only, never automatic truth.

No duplicate `price_history` table is planned initially. Alembic `0003_product_identity` now provides the empty provenance-safe `offer_normalizations`, `canonical_products`, `product_match_candidates` and `offer_product_links` schema. No production offer has been persisted into the identity tables yet. Phase 3Ca now provides corrected Unicode-safe deterministic `normalizer-v1` and a read-only cross-store candidate report over the real production offer dataset; fuzzy similarity remains review-only and confirmed links remain zero. Price history is derived by joining confirmed canonical links to immutable offer observations.

The running API health metadata still reports the previously deployed Phase 2B27 label until the next controlled API code deployment.

## Reviewed runtime pins

- Python `3.13.14-slim-bookworm`
- PostgreSQL `18.4-bookworm`
- Nginx `1.30.4-alpine`
- FastAPI `0.139.2`
- Pydantic `2.13.4`
- SQLAlchemy `2.0.51`
- Psycopg `3.3.4`
- Alembic `1.18.5`

These are deployed/reviewed pins, not a claim that every pin will always remain the newest upstream release.
