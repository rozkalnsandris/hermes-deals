<p align="center">
  <img src="backend/app/ui/assets/deals-logo.svg" alt="Hermes Deals project logo" width="112">
</p>

<p align="center">
  <img src="assets/branding/readme-banner.jpg" alt="Hermes Deals project banner" width="960">
</p>

# Hermes Deals

Private, fully custom family shopping-intelligence platform for Andris' household.

<!-- project-progress:start -->
## Project progress

**Overall:** **60%** `████████████░░░░░░░░`

**Overall project progress (07.08.2026):** **+0 percentage points** **(60% → 60%)**

**Store catalogues**
- **Netto:** **36%** `████░░░░░░`
- **Lidl:** **71%** `███████░░░`
- **ALDI Nord:** **60%** `██████░░░░`
- **EDEKA Patzer:** **50%** `█████░░░░░`

**Issues fixed:** **87 total** · **28 during the previous day** — [#44](https://github.com/rozkalnsandris/hermes-deals/issues/44), [#124](https://github.com/rozkalnsandris/hermes-deals/issues/124), [#213](https://github.com/rozkalnsandris/hermes-deals/issues/213), [#215](https://github.com/rozkalnsandris/hermes-deals/issues/215), [#219](https://github.com/rozkalnsandris/hermes-deals/issues/219), [#222](https://github.com/rozkalnsandris/hermes-deals/issues/222), [#223](https://github.com/rozkalnsandris/hermes-deals/issues/223), [#228](https://github.com/rozkalnsandris/hermes-deals/issues/228), [#230](https://github.com/rozkalnsandris/hermes-deals/issues/230), [#231](https://github.com/rozkalnsandris/hermes-deals/issues/231), [#232](https://github.com/rozkalnsandris/hermes-deals/issues/232), [#247](https://github.com/rozkalnsandris/hermes-deals/issues/247), [#249](https://github.com/rozkalnsandris/hermes-deals/issues/249), [#250](https://github.com/rozkalnsandris/hermes-deals/issues/250), [#255](https://github.com/rozkalnsandris/hermes-deals/issues/255), [#261](https://github.com/rozkalnsandris/hermes-deals/issues/261), [#266](https://github.com/rozkalnsandris/hermes-deals/issues/266), [#270](https://github.com/rozkalnsandris/hermes-deals/issues/270), [#273](https://github.com/rozkalnsandris/hermes-deals/issues/273), [#278](https://github.com/rozkalnsandris/hermes-deals/issues/278), [#280](https://github.com/rozkalnsandris/hermes-deals/issues/280), [#294](https://github.com/rozkalnsandris/hermes-deals/issues/294), [#295](https://github.com/rozkalnsandris/hermes-deals/issues/295), [#301](https://github.com/rozkalnsandris/hermes-deals/issues/301), [#303](https://github.com/rozkalnsandris/hermes-deals/issues/303), [#306](https://github.com/rozkalnsandris/hermes-deals/issues/306), [#313](https://github.com/rozkalnsandris/hermes-deals/issues/313), [#318](https://github.com/rozkalnsandris/hermes-deals/issues/318)

_Last updated automatically: 08.08.2026 06:44 Europe/Berlin. [Measurement rules](docs/PROJECT_PROGRESS.md)._
<!-- project-progress:end -->

## Retailer control centers

Each retailer has one canonical living GitHub tracker. Use these issues as the authoritative execution source of truth for current state, completed gates, blockers, next actions and evidence:

- **Netto Marken-Discount 5659 → [#289](https://github.com/rozkalnsandris/hermes-deals/issues/289)**
- **Lidl → [#24](https://github.com/rozkalnsandris/hermes-deals/issues/24)**
- **ALDI Nord → [#165](https://github.com/rozkalnsandris/hermes-deals/issues/165)**
- **EDEKA Patzer 071897 / 587881 → [#26](https://github.com/rozkalnsandris/hermes-deals/issues/26)**

Cross-retailer sequencing and shared completion rules remain in [#39](https://github.com/rozkalnsandris/hermes-deals/issues/39).

## Current status — Phase 5G (B15F)

The custom Hermes Deals stack is active across Netto, Lidl, ALDI Nord and the
family-primary EDEKA Patzer store. It includes immutable retailer evidence,
validated offer persistence, current/upcoming deal views, a family shopping UI,
canonical-product comparison and an auditable Lidl review workflow.

Current primary evidence chains:

- Netto: `selected store cookie -> store page -> Publitas viewer/API -> official
  prospect PDF validity -> immutable manifest -> OfferCandidate`
- Lidl: `store-bound flyer JSON/PDF -> immutable SourceSnapshot -> page evidence
  -> parser/OCR -> review queue -> controlled approval -> OfferCandidate`
- ALDI Nord and EDEKA: `official structured/store source -> immutable snapshot
  -> retailer parser -> OfferCandidate`

The 2026-07-30 read-only runtime audit found Alembic at
`0006_unit_basis_pricing (head)`, verified all referenced raw snapshot hashes,
and found no duplicate source identities, invalid price windows or broken
review-state invariants. Product identity currently contains reviewed canonical
links; fuzzy similarity remains candidate evidence only.

### Implemented foundation

- PostgreSQL 18 + SQLAlchemy 2 + Psycopg 3 + Alembic
- FastAPI + Pydantic `OfferCandidate` contract
- immutable raw retailer snapshots and provenance reports
- Netto parser and persisted family-primary offers
- ALDI Nord structured collector and persisted offers
- EDEKA Patzer store-aware collector and persisted offers
- Lidl public flyer API discovery and content-addressed canonical snapshot
- Lidl Review UI, provenance-bound previews and controlled approval gates
- current/upcoming deal API with server-side pagination
- canonical product links, derived price history and basket comparison
- Nginx single-origin `/`, `/api`, `/ws` layout
- Docker Compose on Raspberry Pi 5
- regression/unit tests and exact-running-image verification gates

### Safety rules

- raw retailer evidence is immutable;
- PostgreSQL is the source of truth;
- a retailer parser cannot bypass `OfferCandidate` validation;
- Lidl review/correction candidates are never silently promoted;
- deterministic IDs make the approved write set repeatable;
- DB-level `(snapshot_id, source_offer_id)` uniqueness and PostgreSQL
  conflict-safe inserts preserve idempotence;
- retailer/store identity and validity dates must come from explicit source
  evidence, never URL-number or calendar-week inference.

See `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, and `docs/CODE_REVIEW_2026-07-24.md`.

### Product identity

`OfferCandidate` remains an immutable retailer price observation. Phase 3 adds a separate, versioned identity layer:

`OfferCandidate -> OfferNormalization -> ProductMatchCandidate -> confirmed OfferProductLink -> CanonicalProduct`

Multiple match candidates and rejected decisions must remain auditable; a final confirmed link is stored separately. GTIN is the strongest exact trade-item identifier when explicit source evidence and a valid check digit are available. Retailer-local SKU/article/product IDs remain source-local evidence. Text similarity and PostgreSQL `pg_trgm` are candidate-generation tools only, never automatic truth.

No duplicate `price_history` table is used. Price history is derived by joining
confirmed canonical links to immutable offer observations. Multiple match
candidates and rejected decisions remain auditable; a confirmed link is stored
separately.

## Reviewed runtime pins

- Python `3.13.14-slim-bookworm`
- PostgreSQL `18.4-bookworm`
- Nginx `1.30.4-alpine`
- FastAPI `0.139.2`
- Pydantic `2.13.4`
- SQLAlchemy `2.0.51`
- Psycopg `3.3.4`
- Alembic `1.18.5`
- HTTPX2 `2.7.0` for Starlette/FastAPI test clients
- pypdf `6.14.2` for official prospect validity evidence

These are deployed/reviewed pins, not a claim that every pin will always remain the newest upstream release.

## Local maintenance

- `make clean` removes only generated Python/lint/test caches under `backend/`
  and `tools/`.
- `make test` runs the backend regression suite in the active API container.
- `make verify` runs the full Compose, migration, dependency, regression and
  Nginx health gate.

`make clean` deliberately preserves `data/raw/`, `audit/`, `.codex/evidence/`,
local databases and backup archives.

## Shared ingress ownership

`deals.rozkalns.net` is an Access-protected published application, but the
shared Cloudflare Tunnel connector is **not** part of Hermes Deals.

- `RPi5_main` owns the host systemd `cloudflared.service` and its credential;
- Cloudflare remotely manages the published route and Access policy;
- Hermes Deals owns only its application origin and its local/public health
  verification;
- Hermes Deals deploy, rollback, diagnostics and monitoring must never install,
  restart, replace, reconcile or roll back the shared connector;
- no shared Tunnel credential belongs in this repository, its Compose runtime,
  GitHub issues/PRs or deployment evidence.

A Tunnel/public-edge failure may be diagnosed from this repository, but any
connector lifecycle action belongs to host infrastructure. Historical incident
instructions that assumed an application-owned Cloudflared runtime are
superseded by this boundary.

## Operations runbooks

- [Cloudflare Access service authentication for automated deploy checks](docs/operations/CLOUDFLARE_ACCESS_SERVICE_AUTH.md) — diagnose Access sign-in HTML, configure Service Tokens and GitHub secrets, verify automatic RPi5 deploys, and rotate credentials safely.