# AUTO-RUN FULL Queue v1 — Hermes Deals A8 Simple LIVE canary preparation

Status: `LIVE_CANARY_READY` at source-policy level.

Canonical consumer policy: `.github/auto-run-full-queue-v1.json`.
Consumer adoption manifest: `.github/auto-run-full-queue-adoption-v1.json`.
Fixed Simple LIVE operation contract: `policy/simple-live-origin-path-audit-v1.json`.
Shared contract pin: `rozkalnsandris/ops-workflows@55c8f9a09a9ff33870fe1bb3d6800b49fa315f2a`.
A7 migration tracker: `#876`.
A8 source tracker: `#879`.

A7 established the source-only Queue canary. A8 changes only the reviewed final-live source binding: Queue source+merge authority remains separate from LIVE authority, and no runtime or production operation is enabled or invoked by this source change.

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

Migration trackers `#876` and `#879`, this document, the adoption manifest, and merged source policy are not Queue activation authority by themselves.

Before the first queued source mutation, the activation must persist the shared A3 durable authorization receipt using schema `rozkalns.auto-run-full-queue-auth.v1`. The receipt binds at least the Queue identity, exact repository identity, owner identity, exact shared contract SHA, activation `main` SHA, consumer-rules digest, ordered issue identities and their frozen scope digests, with authority values `source=true`, `merge=true`, `live=false`.

After the receipt is durable, `main` must be re-read and must satisfy the shared post-receipt stability barrier before source authority becomes usable. Scope, rules, repository identity, or trust-boundary drift fails closed.

Only the one `ACTIVE` issue may consume Queue source or merge authority. The ordered set cannot be silently extended, skipped, reordered, or replaced after activation.

## Source and merge envelope

For the frozen ordered set, Queue authority is limited to source/docs/tests/policy work and the guarded GitHub source lifecycle needed to converge each active item. Before every merge, freshly verify:

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

`READY` does not auto-activate a Queue. `STOPPED` does not auto-resume. A8 adds no event/watchdog/controller executor.

## A8 fixed Simple LIVE canary

A8 selects exactly one owner-driven final-live operation for the canary:

- mode: `SIMPLE_LIVE_OWNER_DRIVEN`;
- operation: `hermes-deals.origin-path-audit.v1`;
- target: `hermes-deals-origin-path-audit`;
- consumer contract: `policy/simple-live-origin-path-audit-v1.json`;
- trusted-runtime registry source: immutable `rozkalnsandris/RPi5_main@6ca47e656edab8a06ad4d5116f9015efa1ab2e76`;
- shared Simple LIVE source contract: immutable `rozkalnsandris/ops-workflows@55c8f9a09a9ff33870fe1bb3d6800b49fa315f2a`.

The selected operation is STRICT and bounded to at most one `READ_ONLY_AUDIT_INVOCATION`. It excludes production database writes, production deployment/cutover, restart/configuration mutation, parser or collector behavior changes, runner registration/deregistration, GitHub App/credential/permission changes, arbitrary command/path/argv/environment authority, and undeclared retry/rollback/cleanup/alternate paths.

This operation is deliberately not the existing `deploy-main.yml` self-hosted production deployment path.

## Simple LIVE Ready and owner decision

`LIVE_CANARY_READY` is a source-policy phase. It does **not** claim that the RPi5 executor is currently enabled, that a runtime baseline is currently acceptable, or that an invocation is presently eligible.

After an actual Queue reaches `QUEUE_SOURCE_COMPLETE`, a future controller must freshly reconstruct all Simple LIVE evidence before asking the owner for a decision, including:

- exact final consumer `main` SHA and required exact-main CI;
- completed Queue chain and current repository rules;
- digest of the reviewed consumer operation contract;
- exact operation/target identity and immutable shared/RPi5 source identities;
- fresh expected baseline from resolver `hermes-deals.origin-path-registration.v1`;
- fresh read-only preflight digest;
- fresh trusted-runtime eligibility for the selected RPi5 operation;
- allowed mutation class `READ_ONLY_AUDIT_INVOCATION` with maximum total mutations `1`;
- all explicit exclusions.

The resulting payload must conform to `rozkalns.simple-live-ready.v1`. The Ready envelope is evidence, not authority.

The only Simple LIVE owner command is:

`LIVE <binding_sha256>`

A bare `LIVE` is invalid. Queue completion, source merge, `START`, `turpini`, issue `#879`, historical authorization, or a Ready envelope never grants LIVE.

Immediately before any first state-changing operation, the exact binding must be rebuilt from fresh authoritative evidence. Any SHA, target, operation, rules, baseline, preflight, runtime-eligibility, mutation-budget, or exclusion drift requires STOP and a new owner decision.

## Deferred RPi5 boundary

The canary uses the existing deferred RPi5 trust boundary. A valid future Simple LIVE decision still must be materialized through `LIVE_AUTH_V1` before the trusted RPi5 executor may perform the fixed operation.

A8 source preparation does not create a Ready envelope, create LIVE-AUTH, enable the executor, invoke the operation, install or modify host state, mutate credentials/permissions, or mutate production.

The consumer contract is pinned to the reviewed RPi5 registry source, but runtime eligibility must be freshly proven later. If that mapping or eligibility cannot be proven, the result is `BLOCKED`, not permission to improvise another execution path.

## Auto-Live compatibility

For `hermes-deals.origin-path-audit.v1` on `hermes-deals-origin-path-audit`, A8 selects owner-driven Simple LIVE as the only Queue final-live owner. Auto-Live may not independently own the same operation/target transition.

Existing Auto-Live source primitives and other operations remain unchanged. This A8 binding does not disable repository-wide compatibility behavior and does not migrate unrelated deployment targets.

## Production and authority boundary

Queue authority always has `live=false`.

Neither Queue activation nor Queue merge authorizes production deploy, production database or Review/publication writes, retained/source-evidence mutation, retailer runtime execution, replay/APPLY, scheduler/systemd/host/container mutation, RPi5 executor enablement/invocation, Cloudflare mutation, secrets/credentials/permissions/repository-settings changes, branch-protection/ruleset changes, or any other LIVE mutation.

`ops-workflows` remains shared GitHub-side policy only: it neither executes Hermes Deals production nor stores production credentials. The RPi5 trusted production/host boundary remains authoritative.

## Verification

The consumer workflow `.github/workflows/auto-run-full-queue-adoption-guard.yml` continues to call the shared A6 reusable guard using immutable exact SHA `55c8f9a09a9ff33870fe1bb3d6800b49fa315f2a` with read-only repository permission.

Repository CI verifies the local manifest, exact shared pin, explicit routing, one-ACTIVE/frozen-order semantics, mode mutual exclusion, #814 separation, exact-head merge guards, fixed Simple LIVE operation/target binding, immutable RPi5 registry source identity, one-operation mutation ceiling, deferred LIVE-AUTH requirement, no double ownership with Auto-Live, and the no-runtime-mutation A8 source boundary.
