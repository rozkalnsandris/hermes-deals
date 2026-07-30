# Hermes Deals roadmap

- Phase 1: foundation + source feasibility — done
- Phase 2A: Netto parser + persisted offers — done
- Phase 2B1–2B18: Lidl discovery, OCR, precision, shadow mapping and immutable source binding — done
- Phase 2B19–2B27: Lidl controlled persistence + idempotence/concurrency/read-isolation hardening — done
- Phase 2B42: controlled fifth Lidl offer (Penne Rigate) with corrected-price/name provenance — done
- Phase 2C: ALDI Nord structured collector + persistence — done; scheduled-run acceptance remains an operational audit
- Phase 2D: EDEKA Patzer store-aware collector + persistence — done; scheduled-run acceptance remains an operational audit
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
