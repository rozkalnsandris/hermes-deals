# Connected north-star UI acceptance — 2026-10-01

Local FastAPI `/ui/home/`, isolated SQLite test database, synthetic products explicitly prefixed `TESTS`, `example.invalid` provenance URLs and visible `TESTU DATUBĀZE` marker. These screenshots are layout/interaction evidence only, not real retailer prices or production/PostgreSQL rollout evidence.

- [Desktop, 1440 × 1000](desktop.png): saved list, separate branch baskets, real-provider history projection.
- [Mobile, 412 × 892](mobile.png): overview, navigation and offer rows without page overflow.
- [Mobile product detail](detail-mobile.png): compatible-store comparison, history chart and scrollable dated observation table.

Browser acceptance opened the favorite history, inspected four source observations and two compatible store prices, then added the product through its actual HTML form. An initial 403 exposed `Referrer-Policy: no-referrer` suppressing the form Origin. Changing it to `same-origin` preserved strict Origin/CSRF checks and the actual browser POST then redirected successfully to `saved=1`; quantity increased from one to two and persisted on reload.

Validation:

- Full backend regression: **3176 passed, 4 skipped** (3 dependency deprecation warnings).
- After final form-header fix: targeted live UI + demo + price service **57 passed**.
- Lock/registration and live UI focused suite: **43 passed**, including unchanged canary registration rejecting the new application lock.
- Frontend regression: **61 passed**; deterministic W3 build **PASS**.
- Web architecture validator, JavaScript syntax and whitespace diff checks **PASS**.

No production deploy, migration, collector run, source-data mutation or canary registration was executed. Migration 0008 was exercised only in isolated local tests. Recipes/planner still use the separate demonstrator; they are not connected in the database view yet.
