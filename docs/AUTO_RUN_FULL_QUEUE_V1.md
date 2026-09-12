# AUTO-RUN FULL Queue v1 — Hermes Deals source-canary reconciliation

Status: `SOURCE_ONLY_CANARY`. The canonical adoption manifest records `source_canary.status=NOT_PROVEN`, so final LIVE is disabled.

Canonical consumer policy: `.github/auto-run-full-queue-v1.json`.
Consumer adoption manifest: `.github/auto-run-full-queue-adoption-v1.json`.
Dormant Simple LIVE operation contract: `policy/simple-live-origin-path-audit-v1.json`.
Shared contract pin: `rozkalnsandris/ops-workflows@106908294d8515f74efa02d03321883db4b8ab79`.
A7 migration tracker: `#876`.
A8 source-preparation tracker: `#879`.
Current reconciliation: `#898`.

A7 established the Queue consumer source contract and A8 prepared one reviewed owner-driven Simple LIVE operation. Those historical source migrations do not prove that a genuine Queue activation completed a source canary. The hardened shared contract therefore requires explicit machine-readable Queue completion evidence before the adoption phase can advance again.

## Explicit Queue command only

The only Queue activation command recognized by this repository is:

`AUTO-RUN FULL QUEUE hermes-deals #<issue1> ... #<issueN>`

The command must be fresh and explicit in the current owner instruction. It must name `hermes-deals` and contain between 1 and 10 positive issue numbers. Issue numbers are ordered and unique; that frozen order is authoritative for the activation.

Queue mode must never be inferred from `START`, `START hermes-deals`, `turpini`, chat/history, issue labels, open issues, migration issues `#876` or `#879`, controller state, prior receipts, or executor availability.

## Compatibility with single-issue AUTO-RUN FULL

Existing `AUTO-RUN FULL hermes-deals #<issue>` remains available and authoritative for the explicit single-issue form. Its durable controller remains issue `#814` and its policy remains `.github/auto-run-full-v2.json`.

Queue mode is additive. It does not reinterpret, replace, migrate, or reuse issue `#814`. Every Queue activation requires a separate batch/controller issue for its durable authorization and continuation state.

The modes are mutually exclusive while active:

- Queue activation requires the legacy single-issue controller `#814` to be idle.
- A new single-issue FULL activation requires there to be no active Queue controller.
- A conflict is `STOP_MODE_CONFLICT`; authority never transfers from one mode to the other.

The exact Queue prefix must be matched as its own mode. `AUTO-RUN FULL QUEUE ...` is not a multi-argument variant of single-issue `AUTO-RUN FULL ...`.

## Durable Queue authorization

Migration trackers, this document, the adoption manifest, and merged source policy are not Queue activation authority by themselves.

Before the first queued source mutation, the activation must persist the shared durable authorization receipt using schema `rozkalns.auto-run-full-queue-auth.v1`. The receipt binds at least the Queue identity, exact repository identity, owner identity, exact shared contract SHA, activation `main` SHA, consumer-rules digest, ordered issue identities and their frozen scope digests, with authority values `source=true`, `merge=true`, `live=false`.

After the receipt is durable, `main` must be re-read and must satisfy the shared post-receipt stability barrier before source authority becomes usable. Scope, rules, repository identity, or trust-boundary drift fails closed.

Only the one `ACTIVE` issue may consume Queue source or merge authority. The ordered set cannot be silently extended, skipped, reordered, or replaced after activation.

## Source-canary evidence and phase truth

The adoption manifest is the machine-readable current phase record. At this revision it contains the exact fail-closed evidence state:

- `adoption_phase=SOURCE_ONLY_CANARY`;
- `source_canary.status=NOT_PROVEN`;
- no Queue id, controller issue, ordered issue set, activation/final `main` SHA, authorization receipt digest, or completion receipt digest is claimed;
- `final_live.mode=DISABLED`;
- Queue source and merge capability declarations remain present, while Queue LIVE authority remains false.

Do not infer `QUEUE_SOURCE_COMPLETE` from the historical A7 or A8 source migrations, ordinary FAST work, a single-issue FULL run, a merged PR, an issue closeout, CI success, or a handoff note. A future phase advance to `LIVE_CANARY_READY` requires a genuine Queue activation to complete source work and provide the exact evidence fields required by the shared adoption schema.

No source change may manufacture, backfill, or guess those evidence values merely to unlock a later phase.

## Source and merge envelope

For a freshly authorized frozen Queue set, Queue authority is limited to source/docs/tests/policy work and the guarded GitHub source lifecycle needed to converge each active item. Before every merge, freshly verify:

- the exact active issue and frozen scope digest;
- current repository rules and Queue authorization receipt;
- the exact canonical PR and exact current head SHA;
- required exact-head CI;
- reviews and unresolved actionable threads;
- current mergeability;
- `expected_head_sha` binding.

After merge, freshly verify the exact new `main` and applicable exact-main CI before advancing the Queue cursor. External `main` drift, rules drift, scope drift, authorization ambiguity, or an error after mutation begins is fail-closed.

## Resume semantics

GitHub events, comments, CI completion, review activity, manual continuation, or a scheduled watchdog may only wake a controller. They are never authority and never directly advance the Queue cursor. Every wake must reconstruct from fresh canonical GitHub state.

`READY` does not auto-activate a Queue. `STOPPED` does not auto-resume. This consumer adds no event/watchdog/controller executor through Queue adoption.

## Dormant reviewed Simple LIVE operation

The prior A8 source work remains useful as a dormant reviewed future operation contract, but it is not the currently selected final-live phase:

- prepared mode: `SIMPLE_LIVE_OWNER_DRIVEN`;
- operation: `hermes-deals.origin-path-audit.v1`;
- target: `hermes-deals-origin-path-audit`;
- consumer contract: `policy/simple-live-origin-path-audit-v1.json`;
- trusted-runtime registry source: immutable `rozkalnsandris/RPi5_main@6ca47e656edab8a06ad4d5116f9015efa1ab2e76`;
- shared source contract: immutable `rozkalnsandris/ops-workflows@106908294d8515f74efa02d03321883db4b8ab79`.

The operation contract itself continues to require Queue source completion, exact final `main`, exact-main CI and separate LIVE authority. Its prepared mode does not override the canonical adoption manifest's current `final_live.mode=DISABLED` state.

The operation is STRICT and bounded to at most one `READ_ONLY_AUDIT_INVOCATION`. It excludes production database writes, production deployment/cutover, restart/configuration mutation, parser or collector behavior changes, runner registration/deregistration, GitHub App/credential/permission changes, arbitrary command/path/argv/environment authority, and undeclared retry/rollback/cleanup/alternate paths.

This operation is deliberately not the existing `deploy-main.yml` self-hosted production deployment path.

## Future Simple LIVE gate

Only after a genuine Queue reaches `QUEUE_SOURCE_COMPLETE` may a separately reviewed source transition advance the adoption phase and select a final-live mode. That future source transition must preserve the exact source-canary evidence rather than replacing it with a phase label.

If `SIMPLE_LIVE_OWNER_DRIVEN` is selected later, a future controller must reconstruct all required evidence from fresh authoritative state, including exact final consumer `main`, required exact-main CI, Queue completion evidence, operation-contract digest, consumer-rules digest, expected baseline, read-only preflight digest, trusted-runtime eligibility, exact operation/target and the bounded mutation/exclusion set.

A resulting `rozkalns.simple-live-ready.v1` envelope is evidence, not authority. The only prepared Simple LIVE owner command remains:

`LIVE <binding_sha256>`

A bare `LIVE` is invalid. Queue completion, source merge, `START`, `turpini`, issue `#879`, historical authorization, or a Ready envelope never grants LIVE.

Immediately before any future first state-changing operation, the exact binding must be rebuilt from fresh authoritative evidence. Any SHA, target, operation, rules, baseline, preflight, runtime-eligibility, mutation-budget, or exclusion drift requires STOP and a new owner decision.

## Deferred RPi5 boundary

The prepared operation uses the existing deferred RPi5 trust boundary. A valid future Simple LIVE decision would still need to be materialized through `LIVE_AUTH_V1` before the trusted RPi5 executor could perform the fixed operation.

Current source reconciliation does not create a Ready envelope, create LIVE-AUTH, enable the executor, invoke the operation, install or modify host state, mutate credentials/permissions, or mutate production.

The consumer contract remains pinned to a reviewed RPi5 registry source, but runtime eligibility must be freshly proven at the future live gate. If that mapping or eligibility cannot be proven, the result is `BLOCKED`, not permission to improvise another execution path.

## Production and authority boundary

Queue authority always has `live=false`.

Neither Queue activation nor Queue merge authorizes production deploy, production database or Review/publication writes, retained/source-evidence mutation, retailer runtime execution, replay/APPLY, scheduler/systemd/host/container mutation, RPi5 executor enablement/invocation, Cloudflare mutation, secrets/credentials/permissions/repository-settings changes, branch-protection/ruleset changes, or any other LIVE mutation.

`ops-workflows` remains shared GitHub-side policy only: it neither executes Hermes Deals production nor stores production credentials. The RPi5 trusted production/host boundary remains authoritative.

## Verification

The consumer workflow `.github/workflows/auto-run-full-queue-adoption-guard.yml` calls the shared reusable guard using immutable exact SHA `106908294d8515f74efa02d03321883db4b8ab79` with read-only repository permission.

Repository tests verify the exact shared pin, the `SOURCE_ONLY_CANARY` / `NOT_PROVEN` manifest state, explicit routing, one-ACTIVE/frozen-order semantics, mode mutual exclusion, #814 separation, exact-head merge guards, current final-LIVE disablement, the dormant Simple LIVE operation/target binding, immutable RPi5 registry identity, one-operation mutation ceiling, deferred LIVE-AUTH requirement, no double ownership with Auto-Live, and the no-runtime-mutation source boundary.
