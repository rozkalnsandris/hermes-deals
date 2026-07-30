# Hermes Deals architecture

## Current direction

Current implemented runtime:

- FastAPI-served family and review HTML interfaces
- Nginx single-origin ingress (`/`, `/api`, `/ws`)
- FastAPI / Python 3.13
- PostgreSQL 18
- SQLAlchemy 2 + Psycopg 3 + Alembic
- Python collectors, HTTP/JSON first; Playwright only for source investigation
- Docker Compose on the Raspberry Pi 5

Longer-term client direction:

- SvelteKit + Tailwind CSS 4 PWA; deployment mode will be acceptance-tested rather than locked prematurely
- IndexedDB for offline client queue/cache
- WebSocket for live notifications, never as the source of truth
- Cloudflare Tunnel only after local acceptance

## Data truth

PostgreSQL is the source of truth. WebSocket is an event channel. Browser IndexedDB is a local cache/operation queue. Raw retailer responses are immutable evidence used for provenance and parser regression tests.

## Single origin

`deals.rozkalns.net` will expose `/` frontend, `/api/*` FastAPI and `/ws/*` WebSocket. No separate public API subdomain is planned.

## Collector isolation

A broken Lidl parser must not break Netto, ALDI Nord, EDEKA, shopping lists, recipes, or the API. Every retailer has an isolated adapter and raw snapshot chain.

## Offer boundary

Retailer-specific parsing ends at the validated `OfferCandidate` contract. The normalizer, price history and scoring layers must not consume unvalidated parser dictionaries directly.

## Lidl provenance and persistence invariants

The current Lidl pipeline deliberately separates evidence collection from DB persistence:

1. public flyer JSON is retained as immutable raw evidence;
2. a content-addressed canonical flyer file is bound to a real `SourceSnapshot`;
3. OCR/semantic/math stages produce audit reports without offer writes;
4. only explicitly approved strict-ready evidence profiles can enter controlled persistence: `math_verified + dual-PSM`, or the narrowly audited `math_corrected_verified` path with corrected-price and name-recovery provenance;
5. persistence verifies the canonical snapshot SHA again immediately before write;
6. row IDs are deterministic from `snapshot_id + source_offer_id`;
7. unexpected pre-existing rows abort instead of being replaced;
8. review/correction candidates cannot be silently rewritten into persisted prices; corrected evidence requires an explicit audited promotion contract and preserves original OCR provenance.

Offer persistence now enforces database-level uniqueness on `(snapshot_id, source_offer_id)` and uses PostgreSQL `ON CONFLICT DO NOTHING` with exact post-insert validation. Application-level deterministic/exact-set checks remain as an additional invariant rather than the only concurrency defense.

## Product identity and normalization

Retailer observations and product identity are separate concerns.

`OfferCandidate` is an immutable price observation. The identity pipeline is:

`OfferCandidate -> OfferNormalization -> ProductMatchCandidate -> OfferProductLink -> CanonicalProduct`

`OfferNormalization` is versioned and records normalized name/brand, parsed package quantity/unit/pack count, explicit GTIN when available, category hints and evidence.

`ProductMatchCandidate` is many-per-offer and preserves matcher version, method, confidence, evidence and review decision. Rejected candidates stay in history.

`OfferProductLink` stores only the final confirmed link. It is not a pending/rejected candidate table.

GTIN is the strongest exact trade-item identifier when explicitly provided by source evidence and checksum-valid. Retailer-local SKU/article/product IDs are provenance only. Image filenames and arbitrary digit sequences are never inferred as GTIN.

Exact normalized fields/package compatibility may generate strong candidates. PostgreSQL `pg_trgm` and other fuzzy similarity are candidate generation only, never automatic truth.

`CanonicalProduct` represents a specific purchasable trade-item/package. A later shopping-concept/ProductGroup layer represents substitutable intent such as “milk”.

## Price history

No duplicate price-history table is created initially. Price history is derived by joining confirmed canonical links to immutable `offer_candidates`, ordered by validity and collection time.

## Client / UI direction

The target remains a fully custom SvelteKit + Tailwind CSS 4 PWA. Bits UI may provide headless accessible primitives. IndexedDB/Dexie is offline cache + outbox; PostgreSQL/FastAPI remains source of truth; WebSocket is invalidation/change signalling.

Correctness must not depend on Background Sync. Offline mutations retry on app launch, `online`, focus and manual refresh. SvelteKit SSR/`adapter-node` versus a more static deployment is acceptance-tested on the real RPi/mobile path. Shopping mode may optionally use Screen Wake Lock where supported.

Primary mobile navigation: Today, List, Deals, Plan, More. Shopping-list entry always allows free text. Canonical product linkage is optional. Later basket scoring includes store-trip friction, preferred stores, app/coupon requirements, validity, package fit, match confidence and historical baseline.

## Transaction model

SQLAlchemy sessions use explicit commit boundaries for persisted source snapshots and offers. Deployment rollback is an additional operational safety layer, not a substitute for DB transaction semantics. Concurrent identical writers have been validated to converge without duplicate rows, divergent writers are rejected by exact payload checks, and failed multi-row writes roll back atomically.
