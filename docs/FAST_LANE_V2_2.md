# FAST-LANE v2.2 Composite — Hermes Deals

This is the active local FAST-LANE startup contract. The older versioned filename is retained only for backward compatibility and is not startup authority.

## Core rule

**The human approves the RISK / DECISION. Automation executes the TECHNICAL STEPS.** STRICT describes mutation risk, not the number of approval prompts. Read-only checkpoints do not create owner gates.

## Lane role

FAST-LANE is the **safe discovery, audit and non-FULL continuation lane**. Use it for `START`, `turpini`, diagnosis, audits, scope/DoD definition and work that should stop at a decision boundary.

For a concrete implementation issue with a usable Definition of Done, the preferred implementation lane is `AUTO-RUN FULL hermes-deals #<issue>` under `.github/auto-run-full-v2.json` and `docs/AUTO_RUN_FULL_V2.md`.

FAST never infers FULL authority.

## Command routing invariant

Bare `START`, `START hermes-deals`, `turpini`, or equivalent continuation selects normal **FAST-LANE v2.2** operation. It does **not** select `GITHUB-ONLY`, `LIVE-ALL`, or `AUTO-RUN FULL`.

`GITHUB-ONLY` is active only when the owner explicitly includes `GITHUB-ONLY` in the current command, including the documented `git hub only` spelling. `LIVE-ALL` likewise requires an explicit current-command `LIVE-ALL` token.

`AUTO-RUN FULL` is a separate explicit issue-scoped implementation mode and is active only for the exact command form `AUTO-RUN FULL hermes-deals #<positive issue number>`. Its machine contract is `.github/auto-run-full-v2.json`; its human contract is `docs/AUTO_RUN_FULL_V2.md`.

Never infer an explicit mode from `.github/start-github-only.json`, deploy-queue state, handoff/issue continuity, executor availability, historical chat state, controller state, or a prior authorization receipt. Those are state/evidence inputs after command mode has been selected; they are not mode selectors. The machine-readable local dispatcher contract is `.github/start-mode-routing.json`.

## FAST source envelope

`START`, `turpini`, or an equivalent continuation instruction may carry safe source work from fresh canonical GitHub state through Ready: branch, implementation, focused tests, commit/push, Draft PR, CI/review and up to two scope-preserving corrective commits. Batch 2-5 closely related same-risk items when they form one acceptance story. Normal FAST merge remains explicit.

Use FAST to discover/define the implementation issue, acceptance criteria and risk boundary. Once the concrete issue exists, prefer switching to `AUTO-RUN FULL hermes-deals #<issue>` rather than repeatedly driving ordinary implementation with `turpini`.

A valid explicit FULL command is a different owner decision. It freezes one issue-specific source envelope and may carry that source task through exact-head merge without a later literal MERGE message when all AUTO-RUN conditions pass. It never arises from FAST continuation or a prior AUTO-RUN state.

## Human gate budget

Normal FAST delivery has at most two owner gates: **MERGE**, then **COMPOSITE LIVE** only if live work is actually required. CI polling, diff inspection, GET/preflight, evidence refresh, checkout discovery, build preparation, candidate verification and reconciliation are automation steps.

AUTO-RUN FULL changes only the source/merge gate for its exact frozen issue. Hermes Deals STRICT live authority remains a separate explicit owner decision even under AUTO-RUN FULL.

## AUTO-RUN FULL v2 relationship

For an active valid FULL issue:

- GitHub issue + stable owner-identity activation receipt are durable source/merge authority;
- GitHub event-triggered ChatGPT Work is the preferred low-latency PR resume path;
- the hourly Deals AUTO-RUN task remains a watchdog/fallback;
- source/CI/review corrections continue without the FAST two-correction ceiling, subject to the FULL anti-loop ceiling;
- GitHub native auto-merge is preferred only after final exact-head diff/scope review, required CI, actionable-review convergence and mergeability are freshly proven;
- a changed head voids prior merge readiness and requires fresh review/checks before auto-merge may be enabled again;
- repository rulesets remain authoritative and are never bypassed;
- source merge never grants STRICT live authority.

## Composite STRICT

One live authorization may cover the tightly coupled operations required for one bounded rollout when it binds the exact Git SHA, exact target, allowed mutation categories, hard limits, explicit exclusions and expected baseline. All obtainable read-only evidence is collected before asking. Preflight is the first part of the same fail-closed one-shot, not a separate owner session.

Revalidate approved SHA/target/baseline immediately before the first live write and again where drift matters. If another actor changed the target, STOP. Where artifacts/versions apply: pin tooling, build once, verify the exact candidate and deploy that exact artifact/version.

## Local STRICT boundaries

Separate live authorization is required for production deploy, production DB write/migration, Review/publication write, retained/source-evidence mutation, runtime/replay/APPLY or runtime executor invocation, live collector/source execution with write effects, scheduler/systemd/host/container mutation, secrets/credentials/permission/trust-boundary change, Cloudflare/DNS/Access/infrastructure mutation, or equivalent live authority.

`AUTO-RUN FULL` does not silently convert any of those classes into source authority. If the target issue's Definition of Done requires an unapproved STRICT class, AUTO-RUN may converge and merge the source portion, persist exact state, and enter `PAUSED_OWNER_LIVE_GATE`; it must not claim `DONE` until the remaining authorized DoD is actually satisfied.

## Failure and evidence

Normal FAST live authorization is consumed at the first authorized mutation. Any later error/ambiguity requires evidence preservation and STOP; no automatic retry, rollback, cleanup, reset, rebase or alternate mutation path unless explicitly pre-authorized.

AUTO-RUN source work uses failure-fingerprint anti-loop protection rather than the FAST two-correction limit: three materially identical failed attempts without a materially new safe hypothesis terminate as `STOP_ERROR`. Force/history rewrite remains forbidden.

Use one Ready receipt and one final live receipt for normal FAST. AUTO-RUN FULL uses an activation receipt and terminal GitHub receipt as defined in `docs/AUTO_RUN_FULL_V2.md`.

Merge never authorizes deploy/runtime/DB/Review/retained-evidence mutation.
