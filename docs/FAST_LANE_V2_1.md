# FAST-LANE v2.1 Hybrid — Hermes Deals

Hermes Deals adopts the shared FAST-LANE v2.1 Hybrid delivery model while retaining its evidence-first retailer/runtime safety rules.

## FAST

Typical FAST work includes:

- documentation and roadmap alignment;
- parser/source code and deterministic fixtures/tests that do not perform live writes;
- UI/API source changes without production activation;
- test-only and behavior-preserving refactors;
- source code for a future gated runtime operation, provided the operation itself is not invoked.

An explicit owner command such as `FAST #702 līdz Ready` may authorize one coherent source-only batch from fresh GitHub state through Ready. FAST may combine 2-5 closely related same-risk work items when they share one subsystem and acceptance story.

Plain `turpini` keeps its existing narrower meaning: safe/read-only/source-level work only, with no GitHub write authority.

## STRICT

Always separately authorized:

- merge;
- production deploy;
- production DB write or migration apply;
- retained-evidence mutation;
- scraper/runtime activation or live collection with write effects;
- replay/APPLY/runtime executor invocation when separately gated;
- scheduler/systemd/host/container mutation;
- secrets/credentials;
- Cloudflare mutation.

If a STRICT mutation starts and fails or becomes ambiguous, preserve evidence and STOP without retry/rollback/cleanup unless the exact operation contract pre-authorized it.

## Batching and corrections

- FAST may batch 2-5 related same-risk work items.
- Prefer one coherent PR and one CI cycle instead of splitting the same acceptance story into micro-PRs.
- After first publication, at most two scope-preserving corrective commits may address CI/review findings.
- A third correction, a new schema/persistence boundary, or any runtime/production authority expansion requires STOP and new authorization.

## CI

The workflow always starts. Pull-request changed files are classified inside CI.

Phase 1 optimization is deliberately conservative:

- docs-only PR: skip frontend build, release image, backend suite and PostgreSQL contract; run classifier + stable merge gate;
- any source/workflow/config/test change: retain the existing full four-job CI;
- every push to `main`: retain the existing full four-job CI.

Full `main` push CI is intentionally preserved because `deploy-main.yml` currently requires a successful exact-main `push` CI run for the deploy target SHA.

The stable aggregate status is `FAST-LANE Merge Gate`.

## Evidence and continuity

Create one Ready receipt with lane, related work, base/current main, exact head SHA, reviewed scope, CI, unresolved review threads, runtime/deploy/migration classification and exact next gate.

At merge time refresh only mutable evidence. After an explicitly authorized merge, exact-main verification and a compact CURRENT continuity refresh may be performed as part of the merge receipt; merge still does not authorize deploy/runtime/migration.

For the active Kaufland stream, issue #741 is the current continuity location until the roadmap establishes a replacement. Detailed evidence stays in the relevant issues/PRs/CI rather than being duplicated after every micro-step.
