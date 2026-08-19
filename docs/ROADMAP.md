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

Current exact repository baseline after the Kaufland K2 preflight merge: `f47d91778b272210124d050fef4f5a1e25d8071f`.

1. **Progress / roadmap alignment — COMPLETE** — PR #723 squash-merged as `9143a2f41c4885f3f211821542aaa369dea3803c`. V2 remains the historical four-store weighted model; Kaufland remains unweighted until an explicit V3 rebaseline.
2. **Security self-hosted action remediation — COMPLETE** — child PRs #599 → #598 → #725 were merged, then scanner PR #581 was refreshed on the combined `main` and squash-merged as `c2d105969ae793ffeb8d9fc78540362135f510c3`. Final scanner result: `PUBLIC_SELF_HOSTED_MUTABLE_ACTION_COUNT=0` with full CI PASS.
3. **Kaufland K0-K1 — COMPLETE IN SOURCE** — PR #718 squash-merged as `44e2ae511f3ead4c5720f550d0718faf29eca551` after the exact-store live probe passed for Dortmund-Aplerbeck / store `1503`.
4. **Kaufland K2 source/freeze-identity preflight — COMPLETE IN SOURCE** — PR #726 squash-merged as `f47d91778b272210124d050fef4f5a1e25d8071f`. The dedicated live preflight proved 4 exact-store validity families and deterministic freeze identities while keeping retained evidence, raw material, corpus, production DB/Review/publication/deploy, scheduler and systemd writes disabled.
5. **Kaufland K2 retained immutable evidence freeze — NEXT OWNER-ONLY GATE** — issue #701 acceptance still requires retaining the exact evidence bytes/manifest in an explicitly reviewed safe retained location with create-once semantics. This is a write boundary and must not run from generic `turpini`; it requires separate explicit owner authorization bound to the then-current reviewed `main` and approved freeze scope.
6. **ALDI runtime alignment — HOLD** — do not reuse the older exact-SHA RPi5 authorization after `main` moved. Any checkout/registration/root/host action requires a new separately explicit authorization bound to the then-current reviewed SHA.

Production deploys, production DB/Review/publication writes, source apply, retained evidence/corpus writes, scheduler/systemd activation and host/root changes remain separate explicit-authorization gates.

## Delivery roadmap

- Phase 1: foundation + source feasibility — done
- Phase 2A: Netto parser + persisted offers — done
- Phase 2B1–2B18: Lidl discovery, OCR, precision, shadow mapping and immutable source binding — done
- Phase 2B19–2B27: Lidl controlled persistence + idempotence/concurrency/read-isolation hardening — done
- Phase 2B42: controlled fifth Lidl offer (Penne Rigate) with corrected-price/name provenance — done
- Phase 2C: ALDI Nord structured collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2D: EDEKA Patzer store-aware collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2K0–K1: Kaufland Dortmund-Aplerbeck source feasibility and exact-store live-source binding — done in source via #718
- Phase 2K2-preflight: Kaufland exact-store overlapping-campaign identity, validity separation, stable manifest/freeze identity and create-once collision semantics — done in source via #726; actual retained immutable evidence freeze remains the next owner-only #701 gate
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
