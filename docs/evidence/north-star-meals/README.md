# Meal-plan acceptance — 2026-10-01

Isolated local SQLite test database, APP_ENV=test and visible TESTU DATUBĀZE marker. No production writes, migration, source/collector execution or recipe price claims.

Browser flow: open recipes → change tortillas to 2 portions → plan Monday → open planner → update ingredients → open list. Persisted requirements were chicken 250 g, tortillas 4 pieces, pepper 125 g and salad 75 g. State survived a local server restart. With all four prices unknown the total shows “—”, not zero. Forms completed normal 303 redirects.

- [Recipes on mobile, 412 × 892](recipes-mobile.png)
- [Saved ingredients on mobile, 412 × 892](list-mobile.png)
- [Weekly plan on desktop, 1440 × 1000](planner-desktop.png)

Tests: full backend **3185 passed, 4 skipped**, then final UI/meal/demo focused suite **48 passed** after the unknown-total and layout corrections. Architecture validator and git diff whitespace checks passed. Existing deprecation warnings remain. The tests cover two clients, portions, repeated synchronization after removing purchased rows, manual entries, independent weeks, unit preservation, invalid input and legacy household documents.

Known limits: one meal per day, four authored starter recipes, no pantry accounting and no confirmed ingredient-to-retailer mappings or meal prices. Updating a changed plan rebuilds its ingredient requirements; it can restore previously deleted ingredient rows. Manual rows and other weeks remain intact. See `docs/plan/MEALS.md`.
