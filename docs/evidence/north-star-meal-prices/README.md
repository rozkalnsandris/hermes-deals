# Ingredient price acceptance — 2026-10-02

Local isolated SQLite test household, not production retailer evidence. The browser selected a synthetic `TESTS · Piens` 1 l offer at 0.99 EUR for the recipe milk ingredient through the real detail form. The POST returned 303. The omelette's 100 ml requirement then showed 0.10 EUR rounded used value and coverage 1/4; the incomplete full meal price remained unknown.

[Mobile recipe, 412 × 892](mobile.png). Source test prices are explicitly labelled; this image does not establish production freshness or real mapping coverage.

Automated acceptance includes full/partial recipe costs, gram/ml/piece conversions, multipacks, rounding whole packages up, incompatible/ambiguous sizes, app-only and expired prices, unlinking, no global product-link writes, and cross-store basket pack counts. The added cross-store test verifies two 500 g packs produce 6 EUR at one store versus one 1 kg pack at 2 EUR at another, while three unknown ingredients still prevent a full-basket winner.

Full backend regression: 3194 passed, 4 skipped. After the final per-store package-size correction, the live UI/demo/price-service focused suite passed all 75 tests. Web architecture and whitespace checks passed. No migration, production deployment, collector or source mutation was performed. Only the household's own choice is stored; reviewed global identities remain unchanged.
