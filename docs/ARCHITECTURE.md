# Hermes Deals architecture

## Canonical system direction

Hermes Deals is a self-built grocery-deals and price-comparison system. The architecture is intentionally server-driven, evidence-first and online-only.

Current implemented runtime during migration:

- FastAPI-served family and Review interfaces;
- existing Vanilla-JS/CSS family UI that remains in place until each migrated flow has evidence-backed parity;
- Nginx single-origin ingress;
- FastAPI / Python 3.13;
- PostgreSQL 18;
- SQLAlchemy 2 + Psycopg 3 + Alembic;
- Python collectors, HTTP/JSON first; Playwright only for source/browser investigation;
- Docker Compose on the Raspberry Pi 5;
- Cloudflare Access/Tunnel for the family-facing public entry point.

Canonical Web target:

`FastAPI + PostgreSQL + Jinja + HTMX + semantic HTML + plain CSS + minimal Vanilla JS + SSE + Cloudflare Access/Tunnel`.

The detailed normative Web contract is [`docs/WEB_ARCHITECTURE.md`](WEB_ARCHITECTURE.md). Machine-readable invariants are encoded in [`.github/web-architecture-v1.json`](../.github/web-architecture-v1.json).

This decision supersedes the former SvelteKit/Tailwind/IndexedDB/Dexie/offline-first/WebSocket-default client direction. Those technologies are not the canonical target and must not be reintroduced as architecture defaults without an explicit owner architecture decision plus matching contract changes.

## Data truth

PostgreSQL is the application source of truth. Raw retailer responses and retained source artifacts are immutable evidence used for provenance, parser regression and audit.

The browser is never a second source of truth for offers, product identity, comparison state, Review state or shopping-list state. Hermes Deals Web requires connectivity; offline application state and offline mutation queues are out of scope.

## Web presentation boundary

The browser is a thin online presentation and interaction client:

- Jinja renders full pages and reusable HTML fragments;
- HTMX performs incremental authenticated HTTP interactions and swaps server-rendered fragments;
- plain CSS is the styling system;
- Vanilla JavaScript is limited to narrowly justified browser-specific behavior that semantic HTML/HTMX cannot express cleanly;
- ordinary HTTP remains the mutation path;
- Server-Sent Events (SSE) provide server-to-client invalidation/update notifications when real-time behavior is required;
- receiving clients re-read authoritative server state after consequential events;
- WebSocket is not a default architectural dependency.

HTML routes and JSON API routes must project the same shared Python domain/service layer. Pricing, validity, comparison, matching, Review and basket rules must not be duplicated in browser code.

## Single origin

The target remains one family-facing origin at `deals.rozkalns.net`.

Canonical route classes are:

- `/` and human-facing page routes: server-rendered Jinja/HTMX UI;
- `/api/*`: JSON projections over the same shared Python services;
- an SSE endpoint namespace for real-time invalidation/update events when required.

Existing legacy asset or WebSocket paths may remain temporarily during migration, but their existence does not make them part of the target architecture.

## Collector isolation

A broken Lidl parser must not break Netto, ALDI Nord, EDEKA, Kaufland, shopping lists, comparison, Review or the Web/API layer. Every retailer keeps an isolated adapter and immutable raw snapshot/evidence chain.

## Offer boundary

Retailer-specific parsing ends at the validated `OfferCandidate` contract. Normalization, price history, comparison and scoring layers must not consume unvalidated retailer dictionaries directly.

## Lidl provenance and persistence invariants

The Lidl pipeline deliberately separates evidence collection from DB persistence:

1. public retailer source bytes are retained as immutable raw evidence where the approved pipeline requires retention;
2. a content-addressed canonical source artifact is bound to a real `SourceSnapshot`;
3. OCR/semantic/math stages produce auditable results before offer writes;
4. only explicitly approved strict-ready evidence profiles may enter controlled persistence;
5. persistence re-verifies the canonical source identity immediately before write;
6. row IDs are deterministic from source-bound identities;
7. unexpected pre-existing rows abort instead of being silently replaced;
8. review/correction candidates cannot be silently rewritten into persisted prices; corrected evidence requires an explicit audited promotion contract preserving original provenance.

Offer persistence enforces database-level uniqueness on `(snapshot_id, source_offer_id)` and exact post-insert validation. Application-level deterministic/exact-set checks remain an additional invariant rather than the only concurrency defense.

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

## Price history and comparison intelligence

No duplicate price-history table is required initially. Price history is derived by joining confirmed canonical links to immutable `offer_candidates`, ordered by validity and collection time.

The comparison path remains server-side:

`retailer evidence -> OfferCandidate -> normalization/matching -> CanonicalProduct -> comparison/price-history/basket services -> HTML and JSON projections`

Future comparison functionality may include:

- current and historical price comparison;
- unit-price and package-aware comparison;
- validity-window handling;
- retailer/app/coupon eligibility;
- preferred-store constraints;
- historical baseline and deal-quality signals;
- store-trip friction;
- shopping-list and basket/store optimization.

These capabilities extend shared Python/PostgreSQL domain services. They do not require a SPA framework, offline browser database or client-side pricing engine.

## Shopping and family workflow

Primary mobile navigation remains oriented around the household workflow such as Today, List, Deals, Plan and More. Shopping-list entry always permits free text; canonical product linkage is optional.

The family experience is online-only. When multiple clients need prompt synchronization, writes use authenticated HTTP and other open clients are notified through SSE to refresh the relevant authoritative fragments/state.

## Client / UI direction

The canonical Web UI is not a framework rewrite. Migration is incremental:

1. preserve and collect representative W5C browser/Coverage/interaction evidence before destructive CSS cleanup;
2. extract current route/query business logic into shared Python services where needed;
3. introduce Jinja full-page templates and reusable HTMX partials for one bounded flow;
4. migrate Deals, Weekly, product/detail and price-comparison flows incrementally;
5. migrate shopping-list and Review flows while preserving write/publication semantics exactly;
6. add SSE only where a concrete real-time invalidation need exists;
7. remove old client rendering code only after feature, visual, accessibility and mobile parity is evidenced;
8. retain JSON APIs as supported projections over the same shared services;
9. re-evaluate Nginx separately; this Web decision does not imply its removal.

The target CSS hierarchy is `tokens -> base -> layout -> controls -> components -> features -> responsive -> utilities`.

## Explicitly non-canonical Web defaults

Without a new explicit owner architecture decision, the canonical Hermes Deals Web must not drift to:

- SvelteKit, React, Vue, Angular or another SPA framework;
- Tailwind as the canonical styling layer;
- a Node production application server;
- client-side SPA state management;
- IndexedDB or Dexie application state;
- offline outbox, Background Sync or offline mutation reconciliation;
- service-worker business-state caching used to make the application offline-capable;
- mandatory WebSocket transport;
- duplicated browser-side pricing, comparison, matching, validity or Review rules.

Small deterministic build-only tooling remains permissible when pinned, reproducible and justified, provided it does not create a second production application runtime.

## Transaction model

SQLAlchemy sessions use explicit commit boundaries for persisted source snapshots and offers. Deployment rollback is an operational safety layer, not a substitute for DB transaction semantics. Concurrent identical writers must converge without duplicate rows; divergent writers are rejected by exact payload checks; failed multi-row writes roll back atomically.

## Architecture change gate

Changes to the canonical Web framework/runtime model, online-only requirement, source-of-truth boundary, HTTP+SSE real-time model, or introduction of offline application state require an explicit owner architecture decision. Such a change must update `docs/ARCHITECTURE.md`, `docs/WEB_ARCHITECTURE.md`, `.github/web-architecture-v1.json` and the current Web execution tracker together so the repository never carries competing target architectures.
