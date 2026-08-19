# Hermes Deals roadmap

_Last updated: 2026-08-19 (Europe/Berlin)_

## Progress model contract

- Project Progress V2 remains the reviewed **1000-unit weighted baseline**. Its overall percentage and historical milestones must not be retroactively reweighted.
- V2 currently weights four store catalogues: **Netto, Lidl, ALDI Nord and EDEKA Patzer**.
- The current Hermes Deals retailer scope contains **five stores**: Netto, Lidl, ALDI Nord, EDEKA Patzer and **Kaufland Dortmund-Aplerbeck**.
- **Kaufland is not weighted in V2.** The visible V2 overall percentage therefore describes the legacy four-store weighted baseline, not a five-store completion percentage.
- Adding Kaufland to the weighted overall percentage requires an explicit **Project Progress V3 rebaseline** with reviewed weights and migration rules; no V3 weights are invented in this remediation.
- Detailed scope and migration rules: [`docs/PROJECT_PROGRESS_SCOPE.md`](PROJECT_PROGRESS_SCOPE.md).

## Current remediation sequence

1. **Progress / roadmap alignment — PR #723** — make the V2-vs-current-scope boundary explicit without changing historical V2 weights; refresh against current `main` after each preceding merge.
2. **Kaufland K0-K1 — COMPLETE IN SOURCE** — PR #718 squash-merged as `44e2ae511f3ead4c5720f550d0718faf29eca551` after fresh live probe #7 and CI #1515 passed. K2 immutable overlapping-campaign evidence remains the next Kaufland evidence gate under #701.
3. **Security child remediation** — merge only under explicit owner authorization and in the reviewed order **#599 → #598 → #725**; after they land, refresh scanner PR #581 on the combined current `main` and require the mutable-action inventory to reach zero before #581 can become Ready.
4. **ALDI runtime alignment — HOLD** — do not reuse the older exact-SHA RPi5 authorization after `main` moved. Any checkout/registration/root/host action requires a new separately explicit authorization bound to the then-current reviewed SHA.

Production deploys, production DB/Review/publication writes, source apply, scheduler/systemd activation and host/root changes remain separate explicit-authorization gates.

## Delivery roadmap

- Phase 1: foundation + source feasibility — done
- Phase 2A: Netto parser + persisted offers — done
- Phase 2B1–2B18: Lidl discovery, OCR, precision, shadow mapping and immutable source binding — done
- Phase 2B19–2B27: Lidl controlled persistence + idempotence/concurrency/read-isolation hardening — done
- Phase 2B42: controlled fifth Lidl offer (Penne Rigate) with corrected-price/name provenance — done
- Phase 2C: ALDI Nord structured collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2D: EDEKA Patzer store-aware collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2K0–K1: Kaufland Dortmund-Aplerbeck source feasibility and live-source probe — source step merged in PR #718 as `44e2ae511f3ead4c5720f550d0718faf29eca551`; fresh live probe #7 and CI #1515 passed; K2 immutable overlapping-campaign evidence remains next under #701
- Phase 3A: production data / price-history / cross-store matching design audit — done
- Phase 3B0: product-identity truth sync + GTIN/identifier evidence + schema ADR — done
- Phase 3B: versioned offer normalization + canonical products + match-candidate history + confirmed-link schema — done
- Phase 3C: Unicode-safe normalizer-v1 + evidence-backed normalizer-v1.1 package enrichment + review-only candidate report — done
- Phase 3D: reviewed canonical-product seeding + controlled confirmed links + derived price-history API — done
- Phase 3E: first read-only mobile UI vertical slice for products, offers and price history — done
- Phase 4: basic basket comparison — done; family preferences, deal scoring and store-trip optimization remain
- Phase 5: Current/Upcoming family deal UI and auditable Lidl Review workflow — delivered incrementally; household authentication, shared multi-user state and offline/realtime PWA remain
- Stability 0.3.13: exact-running-image verification, Alembic metadata parity, server-side deal pagination, clean test-client lifecycle and Netto PDF validity fallback — done in repository; production deployment remains a separate controlled gate
- Phase 6: recipes + meal planner + ingredient aggregation
