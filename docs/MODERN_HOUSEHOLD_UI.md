# Modern household UI

This redesign builds on GitHub `main` at `5c41a04c4267c2681954c556589f568264b737bb` and the integrated household dashboard from PR #977. It changes the Jinja presentation at `/ui/home/` and its isolated demo, preserving the current server-owned price, offer, household and recipe services.

## Experience

- Forest-green navigation, lime active state, neutral working surfaces and larger typography across all nine household views.
- A week summary showing the existing server-computed list total, item count and recipe count. Unknown prices remain explicit.
- Responsive offer cards with retailer, package, unit price when available, validity, price conditions, source reference price and existing favorite/add actions.
- A desktop workspace with offers and the shared shopping list side by side; actionable offers precede comparison on mobile.
- Updated lists, store comparisons, recipe planning, settings, product details and price history, with the original semantic forms and focus behavior.

`modern.css` is a deliberate presentation layer after the existing stylesheet. Historical CSS remains intact; destructive consolidation requires the separate coverage evidence described in `WEB_ARCHITECTURE.md`. No domain service, database, legacy `/ui` entry point or production setting changes are included. The source Nginx configuration now proxies the existing `/ui/home` and `/ui/home/` namespace to the API; applying this configuration remains a separate rollout step. The CI follow-up updates only the build-time `source-map-js` lock entry from 1.2.1 to 1.2.2 and records two exact historical Docker-image false positives in the existing secret-scan allowlist; scanning rules remain unchanged.

## Local review

From this checkout, install the existing backend and preview requirements in a virtual environment, then run from `backend/`:

```sh
python -m app.north_star_preview
```

Open `http://127.0.0.1:8766/`. This process uses only the existing labeled synthetic fixtures and ephemeral server session, without production connections. Its October 2026 dates and offers are examples, not current retailer evidence. The actual application continues to use `live.html` with the production data service; no demo fallback was added.

## Verification

- Full backend regression: 3227 passed, 4 skipped, 2 existing deprecation warnings, 0 failed (80.07 seconds). Run from `backend/` with the virtual environment on `PATH` and `DATABASE_URL=sqlite+pysqlite:///:memory:` using `python -m pytest -q`.
- Focused preview, live household and ingress contract tests: 83 passed.
- Browser checks: all nine views return HTTP 200 without page-level horizontal overflow at 1440, 412 and 320 pixels.
- Browser interactions: offer addition, favorites, text/retailer filtering, product detail focus, conditional-price explanation and Escape dismissal.
- Browser console: no errors or warnings observed in the checked flows.
- `python3 scripts/validate-web-architecture.py`: PASS.
- `git diff --check`: PASS.

Local screenshots and browser logs are under `.codex/evidence/modern-ui/` (ignored). Production rollout and promotion of the existing household route to the public landing page remain separate from this presentation change.

## CI follow-up

The initial GitHub run passed backend, PostgreSQL and architecture checks, but failed the dependency audit and full-history secret scan. `source-map-js` 1.2.2 resolves the reported GHSA-68fv-2mgg-jv7q audit finding. The two scanner findings are line 7 of `docs/plan/ROLLOUT_PREFLIGHT.md` in commits `5cd9d8bed2e11facd9a9bf8b6a676109bd4a326a` and `11a7391f37effd2ac71aaac85ccb908c81bd2f66`: a public Docker image digest/tag, not authentication material. Exceptions are bound to those immutable commit/file/line/rule identities. No broad pattern exclusion or history rewrite was added.

After the lock correction, `npm audit --audit-level=high` reports zero vulnerabilities, all 61 frontend tests pass, and `npm run build:check` passes.


## Server-rendered navigation

The live household UI now uses HTMX for GET navigation, filters and product details.
Both full documents and incremental responses render the same Jinja shell and call
`build_live_context`; fragments replace the complete household content so badges,
forms and version values stay consistent. Responses vary on `HX-Request` and
`HX-History-Restore-Request` and remain `no-store`. Ordinary navigation and GET
forms continue to work with JavaScript disabled. POST forms are not boosted;
existing CSRF, origin, household version and redirect/error handling remain intact.

HTMX 2.0.11 is vendored unchanged with its license and immutable upstream Git blob
pin, matching the dependency selected in draft PR #953. That PR's separate
`/ui/deals` implementation is not imported or required here. Evaluation and response
script execution are disabled. Browser history snapshots are disabled; Back/Forward
reloads authoritative full pages. A failed incremental GET falls back to its exact
full URL, including submitted filters. POST requests are never retried by this code.

Browser evidence uses the actual `/ui/home/` routes against an isolated in-memory
test database, with explicit `TESTU DATUBĀZE` labeling. Verified:

- fragment navigation, filtering, title/URL updates and dialog focus/Escape return;
- Back restoring filter values from a fresh full document, with no HTMX history cache;
- ordinary POST addition followed by a fresh server-rendered list count;
- all nine views at 1440, 412 and 320 pixels, without horizontal overflow;
- main-content focus after navigation and mobile menu closure/inert state;
- search without JavaScript, and an injected HTMX 503 falling back with filters intact.

Evidence is in ignored `.codex/evidence/modern-ui/htmx-*.log` and `htmx-mobile.png`.
Ingress validation is a source contract test, not a running Nginx or production
canary. The root URL continues to redirect to legacy `/ui`. Landing-page promotion,
SSE, deployment and production acceptance remain separate steps.
