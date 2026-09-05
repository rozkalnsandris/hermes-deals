# Project Progress scope contract

Status: current remediation contract as of 2026-08-19. This document does **not** reweight Project Progress V2 and does not authorize a merge or any production/runtime action.

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

Kaufland source progress now has two merged source milestones:

- PR #718 squash-merged as `44e2ae511f3ead4c5720f550d0718faf29eca551`, proving the K0-K1 exact-store source binding and live probe for Dortmund-Aplerbeck / store `1503`;
- PR #726 squash-merged as `f47d91778b272210124d050fef4f5a1e25d8071f`, adding and live-validating the K2 source/freeze-identity preflight for four exact-store overlapping validity families with deterministic create-once/collision semantics.

These milestones advance the Kaufland workstream but **do not add Kaufland weighting to Project Progress V2**. Issue #701 still has a separate retained immutable evidence acceptance gate: actual raw retained evidence/corpus creation must occur only in an explicitly reviewed safe retained location and only after separate owner authorization. Until that write boundary is completed, K2 retained-evidence acceptance is not claimed.

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
- retained evidence or corpus writes;
- scheduler or systemd activation;
- RPi5 host/root changes.

Those actions require separate explicit owner authorization.
