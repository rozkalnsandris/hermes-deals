# Hermes Deals Web architecture

## Status

This document is the canonical Web presentation architecture contract for Hermes Deals.

The Web target is intentionally server-driven and online-only:

`FastAPI + PostgreSQL + Jinja + HTMX + semantic HTML + plain CSS + minimal Vanilla JS + SSE + Cloudflare Access/Tunnel`.

The purpose is to keep product, retailer, provenance, comparison and review correctness in Python/PostgreSQL while making the browser a thin presentation and interaction client.

## Project goal alignment

Hermes Deals is a self-built grocery-deals and price-comparison system. The Web layer must support, without weakening provenance or data-integrity boundaries:

- trustworthy physical-store retailer offers;
- immutable retailer evidence and validated offer observations;
- canonical product identity and normalization;
- current-price and historical-price comparison;
- unit-price/package-aware comparison;
- retailer/app/coupon/validity constraints;
- shopping-list and later basket/store comparison intelligence;
- Review workflows;
- mobile-first family use;
- real-time updates while online.

None of these goals requires a SPA framework. Comparison, scoring, identity, validity and pricing logic belong in server-side Python domain/services and PostgreSQL, not in browser state.

## Canonical architecture

```text
Retailer sources
      |
      v
immutable source evidence
      |
      v
validated OfferCandidate observations
      |
      v
normalization / canonical identity / comparison services
      |
      v
PostgreSQL (source of truth)
      |
      v
shared Python domain/service layer
      |-----------------------|
      v                       v
Jinja HTML / HTMX          JSON API
      |
      v
FastAPI / Uvicorn
      |
      v
Cloudflare Access / Tunnel
      |
      v
online browser clients
```

HTML and JSON routes must consume the same authoritative Python services. Business rules must never be duplicated in browser code or separately reimplemented for HTML and API routes.

## Rendering and interaction rules

1. Jinja templates render full pages and reusable HTML partials.
2. HTMX performs incremental GET/POST/PATCH/DELETE interactions and swaps server-rendered fragments.
3. Plain CSS is the canonical styling system.
4. Vanilla JavaScript is allowed only for browser-specific behavior that semantic HTML/HTMX cannot express cleanly, for example focus lifecycle, dialogs, small mobile navigation behavior, installation prompts or other narrowly justified browser APIs.
5. Client JavaScript must not become a second business/domain state machine.
6. Server responses remain authoritative after every mutation.

## Online-only contract

Hermes Deals Web requires connectivity. Offline behavior is explicitly out of scope.

The canonical Web architecture therefore does not use:

- IndexedDB as application storage;
- Dexie;
- offline outbox/operation queues;
- Background Sync;
- offline mutation reconciliation;
- offline-first caches containing business state;
- client-side shadow copies of authoritative comparison/list/review state.

A Web App Manifest may be used for installability. A service worker must not be introduced for offline application behavior without a new explicit architecture decision.

## Real-time contract

Real-time UI updates use ordinary HTTP for writes and Server-Sent Events (SSE) for server-to-client invalidation/update signals.

```text
Client A -- POST/PATCH/DELETE --> FastAPI --> PostgreSQL
                                      |
                                      +--> SSE event --> Client B/C
                                                          |
                                                          +--> HTMX fragment refresh
```

Rules:

- writes remain normal authenticated HTTP requests;
- SSE carries invalidation/update events, not source-of-truth business state;
- receiving clients re-read authoritative server state before rendering consequential data;
- polling is acceptable where simpler;
- WebSocket is not part of the canonical architecture and requires a documented bidirectional real-time requirement before introduction.

## Comparison architecture

All price and basket intelligence is server-side.

Typical path:

```text
OfferCandidate
   -> OfferNormalization
   -> ProductMatchCandidate
   -> confirmed OfferProductLink
   -> CanonicalProduct
   -> comparison/price-history/basket services
   -> HTML and JSON projections
```

Future features such as unit-price normalization, historical baseline comparison, preferred-store constraints, app/coupon eligibility, validity windows, store-trip friction and basket optimization must extend shared domain/services rather than create browser-only logic.

## Route/service boundary

Incorrect:

```text
/api/deals -> business logic A
/deals     -> business logic B
```

Required:

```text
                 deals_service()
                    /      \
              HTML route   JSON route
```

The same rule applies to catalog, price comparison, shopping list, Review and future basket intelligence.

## Security defaults

- Jinja auto-escaping remains enabled for untrusted values.
- Retailer/user-provided HTML must never be trusted/rendered raw by default.
- State-changing requests require the repository's CSRF/authentication controls.
- HTMX requests are same-origin by default; cross-origin request expansion requires explicit review.
- Dynamic script evaluation and arbitrary response script execution must not become application dependencies.
- CSP should converge on self-hosted assets and no broad `unsafe-inline` exception merely to preserve legacy code.
- If a URL returns an HTMX fragment for `HX-Request` and a full page otherwise, cache behavior must vary correctly by request mode (for example `Vary: HX-Request` or equivalent route separation) so intermediaries cannot mix fragment/full-page responses.

## Dependency policy

Frontend dependencies must be few, pinned and self-hosted/vendored in the immutable Hermes release where practical. A dependency must solve a demonstrated requirement.

HTMX is the approved interaction library for the canonical server-driven UI.

## Explicitly non-canonical technologies

The following are not part of the Hermes Deals canonical Web target and must not be introduced as architecture defaults without an explicit owner architecture decision and corresponding contract update:

- SvelteKit;
- React;
- Vue;
- Angular or another SPA framework;
- Tailwind as the canonical styling layer;
- a Node production application server;
- client-side SPA state management;
- IndexedDB/Dexie application state;
- offline outbox/Background Sync architecture;
- mandatory WebSocket transport;
- duplicated browser-side pricing/comparison/business rules.

This prohibition does not ban small build-only tooling when it is deterministic, pinned and justified, but build tooling must not create a second production application runtime.

## CSS direction

The target stylesheet hierarchy is:

```text
tokens
base
layout
controls
components
features
responsive
utilities
```

Historical CSS must be consolidated only from representative browser evidence. Do not guess dead CSS from static search alone. W5C evidence remains the required boundary before destructive consolidation.

## Migration strategy

This is not a big-bang rewrite.

1. Preserve and collect representative W5C browser/Coverage/interaction evidence.
2. Extract current route/query business logic into shared Python services where needed.
3. Introduce Jinja templates and HTMX partial endpoints for one bounded flow first.
4. Migrate Deals, Weekly, product/detail and comparison flows incrementally.
5. Migrate shopping-list and Review flows while preserving write semantics exactly.
6. Add SSE only for concrete real-time invalidation needs.
7. Remove the old client renderer only after feature and visual parity is evidenced.
8. Keep JSON APIs as supported projections over the same shared services.
9. Re-evaluate Nginx separately from this frontend decision; its removal is not implied by this contract.

## Acceptance principles

A Web migration increment is acceptable only when:

- retailer/provenance semantics are unchanged;
- authoritative pricing/comparison behavior remains server-side;
- Review/publication semantics are preserved;
- browser interaction is measured on representative flows;
- accessibility and mobile behavior do not regress;
- full-page navigation remains a functional fallback where practical;
- generated/build artifacts are reproducible and tied to the exact immutable release;
- no production/runtime claim is made without current deployed evidence.

## Architecture change gate

Changing the canonical framework/runtime model, adding offline application state, introducing a Node production server, or replacing SSE/HTTP with WebSocket as a default is an architecture decision, not a routine implementation detail. Such a change requires explicit owner approval plus updates to this document and the machine-readable Web architecture contract in the same reviewed change.
