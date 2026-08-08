# Hermes Deals Project Progress V2

Issue: #335

## Purpose

The README progress block answers five separate questions without mixing them:

1. How much of the reviewed Hermes Deals product roadmap is complete?
2. How complete is each retailer catalogue pipeline?
3. How many weighted roadmap percentage points were completed during the previous `Europe/Berlin` calendar day?
4. How many weighted roadmap gates are complete?
5. How many real repository issues were completed in total and during the previous day?

Project progress is **not** calculated from lines changed, commits, test counts, raw issue counts or `closed issues / all issues`.

## Why V2 exists

V1 used a correct but coarse 100-point model. Several large parent roadmap issues owned multiple independent engineering gates. A parent remained open until every gate was finished, so a day with substantial verified work could still render `+0 percentage points`.

V2 keeps the reviewed weighted-roadmap principle but makes progress granular. Large parent trackers remain coordination issues; independently completed child gates can earn their own reviewed weight.

GitHub's native issue hierarchy supports this planning model: parent issues can be broken into sub-issues, and Projects can expose `Parent issue` and `Sub-issue progress` fields. Hermes Deals may use those relationships for navigation, while this repository manifest remains the calculation source of truth so README progress is deterministic and reviewable.

References:

- https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues
- https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/browsing-sub-issues
- https://docs.github.com/en/issues/planning-and-tracking-with-projects/understanding-fields/about-parent-issue-and-sub-issue-progress-fields

## The 100.0-point contract

`docs/project-progress.json` is the reviewed source of truth.

V2 uses **integer tenths of a project percentage point**:

```text
10 units   = 1.0 project percentage point
1000 units = 100.0% project completion
```

Integer units avoid floating-point drift while allowing the README to display one decimal place.

Every category declares `weight_units`, and the sum of all category weights must be exactly `1000`. Every item declares `units`, and the item units inside a category must equal that category's weight exactly.

The generator fails closed if either invariant is violated.

## Weighted gates

Every weighted item is one of two types.

### `fixed`

Already completed foundation work with explicit repository or roadmap evidence. Fixed entries must list non-empty evidence references and are always complete until a normal reviewed PR changes the manifest.

### `issue`

A narrow, auditable gate bound to exactly one GitHub issue number. The gate counts only while that issue is currently closed and is not `not_planned`, duplicate, an excluded placeholder, a pull request, or an excluded generated operational request.

One GitHub issue number may be bound to only one weighted gate in the manifest. This prevents double-counting.

Parent coordination issues can still carry a small final integration weight, but completed child gates should not be hidden behind an all-or-nothing parent closure.

## V2 migration calibration

V2 was introduced after the 2026-08-07 workday exposed the weakness of V1.

The reviewed V2 decomposition is calibrated so that the set of weighted gates completed **before 2026-08-07** represents **600 units = 60.0%**, preserving the last V1 overall baseline rather than manufacturing a progress jump solely from changing the measurement model.

Weighted gates whose real GitHub completion timestamps fall on 2026-08-07 contribute their own V2 units. With the reviewed V2 manifest, those gates add **120 units = 12.0 percentage points**, producing a reconstructed V2 transition of **60.0% -> 72.0%** for that day.

Retailer percentages are intentionally re-based to the gate model and therefore are not directly comparable to the old coarse V1 retailer percentages.

## Store catalogue percentages

Each retailer percentage is calculated independently from its reviewed category:

```text
completed category units / category weight units * 100
```

The result is rounded deterministically to the nearest **0.1%** using integer arithmetic.

Current category bindings are:

- `netto` -> Netto family-primary store `5659` trusted weekly pipeline;
- `lidl` -> Lidl physical-store trusted weekly pipeline;
- `aldi` -> ALDI Nord frozen-evidence and weekly pipeline;
- `edeka` -> EDEKA Patzer trusted regional weekly pipeline.

These values describe engineering/production trust readiness. They do not describe how many offers happened to be present in one flyer.

## Previous-day progress

`Previous day` is the previous complete calendar day in the manifest's IANA timezone (`Europe/Berlin`). The implementation builds the boundary in local time and then converts it to UTC, so 23-hour and 25-hour daylight-saving transition days remain correct.

Previous-day project progress is the sum of V2 units for currently valid issue-backed weighted gates whose GitHub `closed_at` timestamp falls inside that local calendar-day window.

The README shows the value as project percentage points with one decimal place.

This is separate from repository activity counts: an issue can be valid completed work without being a weighted roadmap gate.

## Weighted gate statistics

The snapshot records:

- total weighted gate count;
- completed weighted gate count;
- weighted gates completed during the previous day;
- the exact gate IDs, categories, issue numbers, units and completion timestamps for the previous day.

This makes the daily percentage-point change explainable rather than opaque.

## Issue statistics

`Issues fixed — total` counts valid completed repository issues across the complete GitHub issue inventory.

`Issues fixed — previous day` counts valid completed issues in the previous complete `Europe/Berlin` day.

Both exclude:

- pull requests;
- open or reopened issues;
- `not_planned` and duplicate closures;
- explicitly excluded accidental placeholders;
- generated `[Hermes deploy]` operational request issues.

Issue counts remain an **activity metric**, not the project-completion formula.

## Generated files

`tools/update_project_progress.py` updates only:

- the bounded marker block in `README.md`;
- `docs/project-progress-latest.json`.

The README must contain exactly one pair of markers:

```text
<!-- project-progress:start -->
<!-- project-progress:end -->
```

The generator fails closed if either marker is missing, duplicated or out of order.

The JSON snapshot stores integer units/tenths rather than relying on floating-point values. It also includes the category/item state required to reproduce the displayed percentages.

For deterministic local tests or audits, the tool accepts `--issues-json` so a frozen issue inventory can be supplied without network access. Normal automation uses GitHub's issue API.

## Automation

`.github/workflows/project-progress.yml` runs daily at `06:00` in the IANA timezone `Europe/Berlin` and supports manual execution.

It uses only:

```yaml
permissions:
  contents: write
  issues: read
```

The job runs on a GitHub-hosted runner. It performs no RPi5 execution, production deployment, Docker action, service restart, retailer collection, Review action, publication, or database access/write.

Before committing generated changes, the workflow verifies that its checkout still matches current `origin/main`. A concurrent `main` update causes the run to stop instead of overwriting newer work.

## Updating V2 weights

A weight or gate change requires a normal reviewed PR and must:

1. identify the exact roadmap/scope change;
2. preserve exactly `1000` total units;
3. keep category item units equal to category weight units;
4. avoid binding one issue to multiple weighted gates;
5. explain why the new decomposition is more truthful;
6. update focused tests and the generated baseline when needed;
7. avoid retroactively assigning arbitrary weight merely to make a desired percentage.

When a large parent issue accumulates independently verifiable work, prefer narrow child issues/sub-issues and assign weight to those gates. Keep only the genuinely final integration/rollout work on the parent.

Do not edit the generated README block or latest snapshot independently of the generator contract.
