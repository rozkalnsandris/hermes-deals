# Project Progress scope contract

Status: remediation contract proposed on 2026-08-19. This document does **not** reweight Project Progress V2 and does not authorize a merge or any production action.

## Why this contract exists

Hermes Deals now has five retailer workstreams, while the reviewed Project Progress V2 model was created as a fixed 1000-unit model with four weighted store catalogue categories. Treating the existing V2 percentage as if Kaufland were already included would make the number misleading; inserting an arbitrary Kaufland weight would rewrite historical progress.

## V2 weighted baseline

Project Progress V2 remains the historical weighted baseline used by `docs/project-progress.json`, `docs/project-progress-latest.json`, `README.md` and `tools/update_project_progress.py`.

Weighted retailer categories in V2:

1. Netto
2. Lidl
3. ALDI Nord
4. EDEKA Patzer

The total V2 manifest remains exactly 1000 units. Existing V2 overall percentages and historical milestones must be interpreted against this four-store weighting contract.

## Current retailer scope

The current Hermes Deals retailer scope is:

1. Netto
2. Lidl
3. ALDI Nord
4. EDEKA Patzer
5. Kaufland Dortmund-Aplerbeck

Kaufland is an active project workstream but is **unweighted in Project Progress V2**. Therefore V2's overall percentage is not a five-store project-completion percentage.

At the initial remediation base SHA `0ff4348508471a430ff1ab1cf8791fa952c71508`, Kaufland PR #718 was open. It was subsequently squash-merged as `44e2ae511f3ead4c5720f550d0718faf29eca551` after fresh K0-K1 live probe #7 and full CI #1515 both passed on the reviewed exact head. This completes the K0-K1 source-binding/probe source step; it does **not** add Kaufland weighting to Project Progress V2. Kaufland K2 immutable overlapping-campaign evidence remains a separate next gate under #701.

## V3 rebaseline gate

Kaufland may affect the overall project percentage only after a separate reviewed Project Progress V3 change defines all of the following:

- the complete weighted scope, including whether every retailer receives a dedicated category;
- new weights and the rule that keeps the total internally consistent;
- how V2 history is preserved instead of silently recomputed;
- the effective date / migration point from V2 to V3;
- generator, snapshot, README and tests updated as one atomic contract change;
- explicit evidence that V3 does not grant any production/runtime authorization.

Until that V3 gate is reviewed and merged, V2 remains numerically unchanged and Kaufland progress is tracked through its roadmap/issues/PR evidence rather than a fabricated percentage.

## Operational safety boundary

This scope remediation is repository/documentation-only. It does not authorize:

- merging any pull request;
- production deploys;
- production database, Review or publication writes;
- source apply / collector execution against production state;
- scheduler or systemd activation;
- RPi5 host/root changes.

Those actions require separate explicit owner authorization.
