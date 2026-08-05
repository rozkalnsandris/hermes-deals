# Hermes Deals project-progress measurement

Issue: #116

## Purpose

The README progress block answers three narrow questions:

1. How much of the defined Hermes Deals product roadmap is complete?
2. How many weighted roadmap percentage points were completed during the previous `Europe/Berlin` calendar day?
3. How many real GitHub issues were completed during that day?

It is not a line-count, commit-count, test-count or raw closed-issue ratio.

## The 100-point contract

`docs/project-progress.json` is the reviewed source of truth. Its category weights and item points must total exactly 100.

Every item is one of:

- `fixed`: already completed foundation work with explicit repository or roadmap evidence;
- `issue`: future or completed work bound to exactly one GitHub issue number.

Fixed items do not change automatically. Altering fixed evidence, weights, categories or issue bindings requires a normal reviewed pull request.

Issue-backed points count only while the issue is currently closed and is not classified as `not_planned` or duplicate.

Creating an unrelated issue does not reduce the project percentage.

## Previous-day statistics

The generator calculates the previous complete calendar day in `Europe/Berlin`, including 23-hour and 25-hour daylight-saving transition days.

`Previous day` percentage points are the sum of configured weighted items whose valid issue completion timestamp falls inside that calendar day.

`Issues completed` counts all valid repository issues completed in the same window, not only weighted roadmap issues. It excludes:

- pull requests;
- open or reopened issues;
- `not_planned` and duplicate closures;
- explicitly excluded accidental placeholders;
- generated `[Hermes deploy]` operational request issues.

The excluded numbers and title prefixes are versioned in the manifest.

## Generated files

`tools/update_project_progress.py` updates only:

- the bounded marker block in `README.md`;
- `docs/project-progress-latest.json`.

The README must contain exactly one pair of these markers:

```text
<!-- project-progress:start -->
<!-- project-progress:end -->
```

The generator fails closed if either marker is missing, duplicated or out of order.

The JSON snapshot includes the category breakdown, item completion state, previous-day issue list and generation timestamps.

## Automation

`.github/workflows/project-progress.yml` runs daily at `06:00` in the IANA timezone `Europe/Berlin` and also supports manual execution.

The workflow uses only:

```yaml
permissions:
  contents: write
  issues: read
```

It runs on a GitHub-hosted runner, reads GitHub issue metadata, and commits only the two generated files when their contents differ. It performs no RPi5 execution, production deployment, service restart, retailer processing or database access.

Before committing, the workflow verifies that its checkout still matches current `origin/main`. A concurrent main update causes the run to stop rather than overwrite newer work.

## Updating the model

A weight change must:

1. identify the exact roadmap or scope change;
2. preserve a total of exactly 100 points;
3. explain why the old and new weights are more truthful;
4. update focused tests and the generated baseline;
5. use the normal issue, branch, Draft PR, CI and owner-review workflow.

Do not edit the generated README block or latest snapshot by hand.
