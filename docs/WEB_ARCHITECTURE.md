# Hermes Deals Web architecture

## Status

**Canonical architecture decision — accepted 2026-09-20.**

This document is the normative human-readable Web presentation architecture contract for Hermes Deals. Machine-readable invariants live in [`.github/web-architecture-v1.json`](../.github/web-architecture-v1.json). The system-level summary lives in [`docs/ARCHITECTURE.md`](ARCHITECTURE.md). The active execution roadmap is GitHub issue #319.

The Web target is intentionally server-driven and online-only:

`FastAPI + PostgreSQL + Jinja + HTMX + semantic HTML + plain CSS + minimal Vanilla JS + SSE + Cloudflare Access/Tunnel`.

This decision supersedes the former SvelteKit/Tailwind/IndexedDB/Dexie/offline-first/WebSocket-default direction. Those technologies are not the canonical Hermes Deals Web target.

The purpose is to keep product, retailer, provenance, comparison and Review correctness in Python/PostgreSQL while making the browser a thin presentation and interaction client.

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

None of these goals requires a SPA framework. Comparison, scoring, identity, validity, pricing and basket logic belong in server-side Python domain/services and PostgreSQL, not in browser state.

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
      +------ SSE invalidation/update signals
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

## Source-of-truth boundary

- PostgreSQL is the authoritative application state.
- Immutable retailer evidence is the provenance source for collected/parsed observations.
- Python domain/services own pricing, validity, normalization, comparison, matching, Review and basket semantics.
- Jinja/HTMX/JSON are projections of the same server-side truth.
- Browser state is presentation state only.
- SSE events are notifications, never the source of truth.

## Rendering and interaction rules

1. Jinja templates render full pages and reusable HTML partials.
2. HTMX performs incremental GET/POST/PATCH/DELETE interactions and swaps server-rendered fragments.
3. Plain CSS is the canonical styling system.
4. Vanilla JavaScript is allowed only for browser-specific behavior that semantic HTML/HTMX cannot express cleanly, for example focus lifecycle, dialogs, small mobile navigation behavior, Wake Lock or other narrowly justified browser APIs.
5. Client JavaScript must not become a second business/domain state machine.
6. Server responses remain authoritative after every mutation.
7. Full-page navigation should remain a functional fallback where practical.

## Online-only contract

Hermes Deals Web requires connectivity. Offline behavior is explicitly out of scope.

The canonical Web architecture therefore does not use:

- IndexedDB as application storage;
- Dexie;
- offline outbox/operation queues;
- Background Sync;
- offline mutation reconciliation;
- offline-first caches containing business state;
- client-side shadow copies of authoritative comparison/list/Review state;
- service-worker business-state caching intended to make Hermes function offline.

A Web App Manifest may be used for installability. Installability does not create an offline requirement. A service worker must not be introduced for offline application behavior without a new explicit owner architecture decision.

## Real-time contract

Real-time UI updates use ordinary authenticated HTTP for writes and Server-Sent Events (SSE) for server-to-client invalidation/update signals.

```text
Client A -- POST/PATCH/DELETE --> FastAPI --> PostgreSQL
                                      |
                                      +--> SSE event --> Client B/C
                                                          |
                                                          +--> authoritative fragment/state refresh
```

Rules:

- writes remain normal authenticated HTTP requests;
- SSE carries invalidation/update events, not authoritative business state;
- receiving clients re-read authoritative server state before rendering consequential data;
- polling remains acceptable where simpler and sufficient;
- WebSocket is not part of the canonical architecture and requires a documented bidirectional real-time requirement plus explicit architecture approval before introduction.

Typical real-time use cases include shopping-list changes, Review status changes, publication completion and other UI invalidation signals. Collector/evidence mutation semantics remain separate from Web notification transport.

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

The architecture supports later comparison goals without a frontend rewrite, including:

- current price by retailer/store;
- historical price observations and baselines;
- unit-price normalization such as EUR/kg and EUR/l;
- package-size and pack-count compatibility;
- retailer/store validity windows;
- app/coupon/loyalty eligibility;
- preferred-store constraints;
- deal-quality signals;
- store-trip friction;
- shopping-list aggregation;
- basket/store optimization and comparison.

These features extend shared Python/PostgreSQL domain services rather than create browser-only logic.

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

The same rule applies to catalog, current deals, weekly views, product detail, price comparison, shopping list, Review and future basket intelligence.

## HTML/HTMX response boundary

Where the same URL may return a full page to a normal request and a fragment to HTMX, cache behavior must prevent intermediaries from mixing representations. Use `Vary: HX-Request`, representation-specific cache keys, or separate fragment routes as appropriate.

Fragment endpoints must preserve authentication, authorization, CSRF and domain validation semantics. HTMX must not become a way to bypass normal server boundaries.

## Security defaults

- Jinja auto-escaping remains enabled for untrusted values.
- Retailer/user-provided HTML must never be trusted/rendered raw by default.
- State-changing requests require the repository's authentication/authorization and CSRF controls.
- HTMX requests remain same-origin unless an explicit reviewed requirement says otherwise.
- Dynamic script evaluation and arbitrary response script execution must not become application dependencies.
- CSP should converge on self-hosted assets and no broad `unsafe-inline` exception merely to preserve legacy code.
- Frontend dependencies must be pinned and self-hosted/vendored in the immutable Hermes release where practical.

## Dependency policy

A frontend dependency must solve a demonstrated requirement and must not create a second production application runtime.

HTMX is the approved interaction library for the canonical server-driven UI. Small deterministic build-only tooling is permitted when pinned, reproducible and justified.

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
- service-worker business-state caching for offline behavior;
- mandatory WebSocket transport;
- duplicated browser-side pricing/comparison/matching/validity/Review rules.

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

### Gate 0 — freeze the architecture

- keep this document, `docs/ARCHITECTURE.md`, `.github/web-architecture-v1.json` and issue #319 consistent;
- reject competing target stacks unless an explicit owner architecture decision changes all canonical references together.

### Gate 1 — preserve evidence before destructive cleanup

- collect representative W5C Chrome Coverage across normal deals/weekly/list/detail interactions;
- pair Coverage with interaction and stable visual evidence;
- identify the surviving CSS cascade deliberately;
- do not guess dead CSS from static search alone.

### Gate 2 — establish shared server services

- extract current route/query business logic into shared Python services where needed;
- keep existing JSON behavior stable;
- prove that HTML and JSON projections consume the same service semantics.

### Gate 3 — first Jinja/HTMX vertical slice

- implement one bounded flow first, preferably Deals;
- serve normal full-page HTML plus HTMX fragments;
- preserve URL/filter/sort/pagination semantics;
- verify mobile, keyboard, accessibility and visual behavior.

### Gate 4 — migrate core family flows

Migrate incrementally in this order unless evidence justifies a narrower child sequence:

1. Deals;
2. Weekly;
3. product/detail and price comparison;
4. shopping list;
5. Review.

### Gate 5 — add real-time where justified

- use ordinary HTTP mutations;
- add SSE only for concrete synchronization/invalidation needs;
- keep SSE payloads minimal and non-authoritative;
- verify reconnect behavior and authoritative refresh after reconnect.

### Gate 6 — retire legacy browser rendering

- remove old client rendering only after feature, visual, accessibility and mobile parity is evidenced;
- remove legacy WebSocket/offline assumptions only when no supported path depends on them;
- keep rollback/release integrity intact.

### Gate 7 — hardening and final proof

- complete responsive/accessibility work;
- finalize cache/CSP/security behavior;
- measure representative runtime/browser performance on the exact deployed release;
- complete final production proof only with current evidence.

## Acceptance principles

A Web migration increment is acceptable only when:

- retailer/provenance semantics are unchanged;
- authoritative pricing/comparison behavior remains server-side;
- Review/publication semantics are preserved;
- shopping-list writes remain authoritative server mutations;
- browser interaction is measured on representative flows;
- accessibility and mobile behavior do not regress;
- full-page navigation remains functional where practical;
- generated/build artifacts are reproducible and tied to the exact immutable release;
- no production/runtime claim is made without current deployed evidence.

## Documentation precedence and consistency

For the Web architecture decision, these artifacts must agree:

1. `docs/ARCHITECTURE.md` — system-level architecture;
2. `docs/WEB_ARCHITECTURE.md` — detailed human Web contract;
3. `.github/web-architecture-v1.json` — machine-readable invariants;
4. issue #319 — executable migration roadmap.

If any of these disagree, treat the architecture state as inconsistent and stop architecture-expanding implementation until the conflict is resolved. Historical issues/PRs may describe previous targets but do not override the current canonical contract.

## Architecture change gate

Changing the canonical framework/runtime model, adding offline application state, introducing a Node production server, changing the source-of-truth boundary, or replacing HTTP+SSE with WebSocket as the default is an architecture decision, not a routine implementation detail.

Such a change requires explicit owner approval and must update `docs/ARCHITECTURE.md`, this document, `.github/web-architecture-v1.json` and issue #319 in the same reviewed change. Merge still does not authorize production deploy or runtime mutation.
