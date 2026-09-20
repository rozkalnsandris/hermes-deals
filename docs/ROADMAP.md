# Hermes Deals roadmap

_Last updated: 2026-09-20 (Europe/Berlin)_

## Progress model contract

- Project Progress V2 remains the reviewed **1000-unit weighted baseline**. Its overall percentage and historical milestones must not be retroactively reweighted.
- V2 currently weights four store catalogues: **Netto, Lidl, ALDI Nord and EDEKA Patzer**.
- The current Hermes Deals retailer scope contains **five stores**: Netto, Lidl, ALDI Nord, EDEKA Patzer and **Kaufland Dortmund-Aplerbeck**.
- **Kaufland is not weighted in V2.** The visible V2 overall percentage therefore describes the legacy four-store weighted baseline, not a five-store completion percentage.
- Adding Kaufland to the weighted overall percentage requires an explicit **Project Progress V3 rebaseline** with reviewed weights and migration rules; no V3 weights are invented in this remediation.
- Detailed scope and migration rules: [`docs/PROJECT_PROGRESS_SCOPE.md`](PROJECT_PROGRESS_SCOPE.md).

## Canonical Web direction

The canonical Hermes Deals Web target is server-driven and online-only:

`FastAPI + PostgreSQL + Jinja + HTMX + semantic HTML + plain CSS + minimal Vanilla JS + SSE + Cloudflare Access/Tunnel`.

Normative Web contracts:

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — system-level architecture;
- [`docs/WEB_ARCHITECTURE.md`](WEB_ARCHITECTURE.md) — detailed Web contract and migration plan;
- [`.github/web-architecture-v1.json`](../.github/web-architecture-v1.json) — machine-readable invariants;
- GitHub issue #319 — active execution roadmap.

The former SvelteKit/Tailwind/IndexedDB/Dexie/offline-first/WebSocket-default direction is superseded. Hermes Deals Web requires connectivity and uses ordinary authenticated HTTP writes plus SSE for server-to-client real-time invalidation/update signals. Price comparison, price history, unit/package comparison, app/coupon/validity constraints and future basket/store optimization remain shared Python/PostgreSQL domain responsibilities, not browser business logic.

Architecture drift to a SPA framework, Node production application server, offline application state or WebSocket-default design requires a new explicit owner architecture decision and synchronized updates to all canonical Web contracts.

## Current continuity / priority gates

Mutable execution state is deliberately **not pinned to an old repository SHA in this roadmap**. Before acting, re-read the current GitHub state and use these live continuity trackers together:

- issue #35 — project sequencing / next steps;
- issue #39 — retailer source-truth tracker;
- issue #319 — server-driven Web migration roadmap;
- the exact current child issue/PR and its current-head checks/reviews.

Current audited continuation on 2026-09-20:

1. **Lidl — validated baseline complete; maintenance priority.** Preserve full physical-store booklet correctness, provenance and UI visibility. Do not regress the completed Lidl baseline while advancing other lanes.
2. **Netto #28 — EVIDENCE-WAIT.** The source workflow has genuine unattended Sunday/Monday `00:10 Europe/Berlin` schedule observations. Only real `schedule` evidence and distinct qualifying transitions satisfy acceptance; manual dispatch, synthetic history, replay or canary does not substitute. Do not manufacture evidence to accelerate the gate.
3. **Netto #321 — BLOCKED_DEPENDENCY at an owner/LIVE host gate.** The original Lillet/Melitta/Softlan/Veltins normal-price anchors still lack one exact integrated source/replay/finalizer proof. The remaining authoritative frozen-corpus path requires the already-defined host/root finalizer or an explicit permissions redesign. Do not guess parser heuristics. Any host/root/permission mutation requires separate LIVE authorization.
4. **Kaufland #701 — CLOSED / COMPLETED.** The old roadmap wording that treated the K2 retained-evidence freeze as the next owner-only gate is retired; #701 is no longer a current gate.
5. **Web W5C — COMPLETE via #922 / PR #923.** Representative desktop/mobile Chrome Coverage and interaction/visual evidence found no basis for destructive CSS deletion. Preserve the surviving cascade; unobserved bytes remain unknown/not-exercised or non-rule evidence, not globally dead CSS.
6. **Web M1 — NEXT UNBLOCKED SOURCE/EVIDENCE LANE while Netto waits/is blocked.** Reconcile the already-merged #812 / PR #822 mobile/accessibility source baseline against current `main` with representative browser evidence: five-action mobile navigation, desktop/mobile responsive behavior, keyboard traversal, drawer/detail focus lifecycle, visible focus, reduced motion and absence of the retired legacy zoom workaround. Make only bounded fixes for evidence-proven regressions. If M1 acceptance passes, continue to M2 rather than re-implementing the existing M1 source baseline.
7. **Other retailer/runtime lanes** remain subordinate to #35/#39 and their own evidence/owner/LIVE boundaries; an old exact-SHA runtime authorization must never be reused after `main` moves.

Production deploys, production DB/Review/publication writes, source apply, retained evidence/corpus writes, scheduler/systemd activation, host/root changes, permissions changes and other LIVE mutations remain separate explicit-authorization gates.

## Delivery roadmap

- Phase 1: foundation + source feasibility — done
- Phase 2A: Netto parser + persisted offers — done; #28 unattended-transition acceptance remains evidence-wait and #321 original four-anchor proof remains owner/LIVE-blocked
- Phase 2B1–2B18: Lidl discovery, OCR, precision, shadow mapping and immutable source binding — done
- Phase 2B19–2B27: Lidl controlled persistence + idempotence/concurrency/read-isolation hardening — done
- Phase 2B42: controlled fifth Lidl offer (Penne Rigate) with corrected-price/name provenance — done
- Phase 2C: ALDI Nord structured collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2D: EDEKA Patzer store-aware collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2K0–K1: Kaufland Dortmund-Aplerbeck source feasibility and exact-store live-source binding — done in source via #718
- Phase 2K2: Kaufland exact-store overlapping-campaign identity, validity separation, stable manifest/freeze identity and immutable evidence-freeze lineage — completed through #701; do not treat the retired pre-#701 owner gate as current
- Phase 3A: production data / price-history / cross-store matching design audit — done
- Phase 3B0: product-identity truth sync + GTIN/identifier evidence + schema ADR — done
- Phase 3B: versioned offer normalization + canonical products + match-candidate history + confirmed-link schema — done
- Phase 3C: Unicode-safe normalizer-v1 + evidence-backed normalizer-v1.1 package enrichment + review-only candidate report — done
- Phase 3D: reviewed canonical-product seeding + controlled confirmed links + derived price-history API — done
- Phase 3E: first read-only mobile UI vertical slice for products, offers and price history — done
- Phase 4: basic basket comparison — done; family preferences, deal scoring and store-trip optimization remain
- Phase 5: Current/Upcoming family deal UI and auditable Lidl Review workflow — delivered incrementally; canonical server-driven Web migration is active. W5C evidence is complete, M1 is an acceptance/reconciliation gate over the existing mobile/accessibility baseline, then M2–M8 proceed as bounded child work before M9 production proof
- Phase 6: recipes + meal planner + ingredient aggregation
