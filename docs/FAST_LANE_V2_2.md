# FAST-LANE v2.2 Composite — Hermes Deals

This is the active local FAST-LANE startup contract. The older versioned filename is retained only for backward compatibility and is not startup authority.

## Core rule

**The human approves the RISK / DECISION. Automation executes the TECHNICAL STEPS.** STRICT describes mutation risk, not the number of approval prompts. Read-only checkpoints do not create owner gates.

## Command routing invariant

Bare `START`, `START hermes-deals`, `turpini`, or equivalent continuation selects normal **FAST-LANE v2.2** operation. It does **not** select `GITHUB-ONLY`, `LIVE-ALL`, or `AUTO-RUN FULL`.

`GITHUB-ONLY` is active only when the owner explicitly includes `GITHUB-ONLY` in the current command, including the documented `git hub only` spelling. `LIVE-ALL` likewise requires an explicit current-command `LIVE-ALL` token.

`AUTO-RUN FULL` is a separate explicit issue-scoped mode and is active only for the exact command form `AUTO-RUN FULL hermes-deals #<positive issue number>`. Its machine contract is `.github/auto-run-full-v1.json`; its human contract is `docs/AUTO_RUN_FULL_V1.md`.

Never infer an explicit mode from `.github/start-github-only.json`, deploy-queue state, handoff/issue continuity, executor availability, historical chat state, controller state, or a prior authorization receipt. Those are state/evidence inputs after command mode has been selected; they are not mode selectors. The machine-readable local dispatcher contract is `.github/start-mode-routing.json`.

## FAST source envelope

`START`, `turpini`, or an equivalent continuation instruction may carry safe source work from fresh canonical GitHub state through Ready: branch, implementation, focused tests, commit/push, Draft PR, CI/review and up to two scope-preserving corrective commits. Batch 2-5 closely related same-risk items when they form one acceptance story. Normal FAST merge remains explicit.

A valid explicit `AUTO-RUN FULL hermes-deals #<issue>` command is a different owner decision. It freezes one issue-specific source envelope and may carry that source task through exact-head merge without a later literal MERGE message when all AUTO-RUN merge conditions pass. It never arises from FAST continuation or from a prior AUTO-RUN state.

## Human gate budget

Normal FAST delivery has at most two owner gates: **MERGE**, then **COMPOSITE LIVE** only if live work is actually required. CI polling, diff inspection, GET/preflight, evidence refresh, checkout discovery, build preparation, candidate verification and reconciliation are automation steps.

AUTO-RUN FULL changes only the source/merge gate for its exact frozen issue. Hermes Deals STRICT live authority remains a separate explicit owner decision even under AUTO-RUN FULL.

## Composite STRICT

One live authorization may cover the tightly coupled operations required for one bounded rollout when it binds the exact Git SHA, exact target, allowed mutation categories, hard limits, explicit exclusions and expected baseline. All obtainable read-only evidence is collected before asking. Preflight is the first part of the same fail-closed one-shot, not a separate owner session.

Revalidate approved SHA/target/baseline immediately before the first live write and again where drift matters. If another actor changed the target, STOP. Where artifacts/versions apply: pin tooling, build once, verify the exact candidate and deploy that exact artifact/version.

## Local STRICT boundaries

Separate live authorization is required for production deploy, production DB write/migration, Review/publication write, retained/source-evidence mutation, runtime/replay/APPLY or runtime executor invocation, live collector/source execution with write effects, scheduler/systemd/host/container mutation, secrets/credentials/permission/trust-boundary change, Cloudflare/DNS/Access/infrastructure mutation, or equivalent live authority.

`AUTO-RUN FULL` does not silently convert any of those classes into source authority. If the target issue's Definition of Done requires an unapproved STRICT class, AUTO-RUN may converge and merge the source portion, persist exact state, and enter `PAUSED_OWNER_LIVE_GATE`; it must not claim `DONE` until the remaining authorized DoD is actually satisfied.

## Failure and evidence

Normal FAST live authorization is consumed at the first authorized mutation. Any later error/ambiguity requires evidence preservation and STOP; no automatic retry, rollback, cleanup, reset, rebase or alternate mutation path unless explicitly pre-authorized.

AUTO-RUN source work uses failure-fingerprint anti-loop protection rather than the FAST two-correction limit: three materially identical failed attempts without a materially new safe hypothesis terminate as `STOP_ERROR`. Force/history rewrite remains forbidden.

Use one Ready receipt and one final live receipt for normal FAST. AUTO-RUN FULL uses an activation receipt and terminal GitHub receipt as defined in `docs/AUTO_RUN_FULL_V1.md`.

Merge never authorizes deploy/runtime/DB/Review/retained-evidence mutation.
