# AUTO-RUN FULL Queue v1 — Hermes Deals A7 source-only canary

Status: `SOURCE_ONLY_CANARY`.

Canonical consumer policy: `.github/auto-run-full-queue-v1.json`.
Consumer adoption manifest: `.github/auto-run-full-queue-adoption-v1.json`.
Shared contract pin: `rozkalnsandris/ops-workflows@55c8f9a09a9ff33870fe1bb3d6800b49fa315f2a`.
Migration tracker: `#876`.

## Explicit command only

The only Queue activation command recognized by this repository is:

`AUTO-RUN FULL QUEUE hermes-deals #<issue1> ... #<issueN>`

The command must be fresh and explicit in the current owner instruction. It must name `hermes-deals` and contain between 1 and 10 positive issue numbers. Issue numbers are ordered and unique; that frozen order is authoritative for the activation.

Queue mode must never be inferred from `START`, `START hermes-deals`, `turpini`, chat/history, issue labels, open issues, migration issue `#876`, controller state, prior receipts, or executor availability.

## Compatibility with single-issue AUTO-RUN FULL

Existing `AUTO-RUN FULL hermes-deals #<issue>` remains available and authoritative for the explicit single-issue form. Its durable controller remains issue `#814` and its policy remains `.github/auto-run-full-v2.json`.

Queue mode is additive. It does not reinterpret, replace, migrate, or reuse issue `#814`. Every Queue activation requires a separate batch/controller issue for its durable authorization and continuation state.

The modes are mutually exclusive while active:

- Queue activation requires the legacy single-issue controller `#814` to be idle.
- A new single-issue FULL activation requires there to be no active Queue controller.
- A conflict is `STOP_MODE_CONFLICT`; authority never transfers from one mode to the other.

The exact Queue prefix must be matched as its own mode. `AUTO-RUN FULL QUEUE ...` is not a multi-argument variant of single-issue `AUTO-RUN FULL ...`.

## Durable Queue authorization

The migration tracker `#876`, this document, the adoption manifest, and a merged A7 source PR are not Queue activation authority by themselves.

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

`READY` does not auto-activate a Queue. `STOPPED` does not auto-resume. No event/watchdog/controller executor is added by A7.

## LIVE and production boundary

A7 keeps `final_live.mode=DISABLED`. Queue authority always has `live=false`.

Neither Queue activation nor Queue merge authorizes production deploy, production database or Review/publication writes, retained/source-evidence mutation, retailer runtime execution, replay/APPLY, scheduler/systemd/host/container mutation, RPi5 mutation, Cloudflare mutation, secrets/credentials/permissions/repository-settings changes, branch-protection/ruleset changes, or any other LIVE mutation.

`ops-workflows` remains shared GitHub-side policy only: it neither executes Hermes Deals production nor stores production credentials. The RPi5 trusted production/host boundary is unchanged and any future deferred RPi5 execution still requires the repository's separate `LIVE_AUTH_V1` authority.

A future LIVE canary is a separate migration stage and separate owner decision; A7 does not prepare or consume that authority.

## A7 verification

The consumer workflow `.github/workflows/auto-run-full-queue-adoption-guard.yml` calls the shared A6 reusable guard using the immutable exact SHA `55c8f9a09a9ff33870fe1bb3d6800b49fa315f2a` with read-only repository permission.

Repository CI also verifies the local manifest, exact shared pin, explicit routing, one-ACTIVE/frozen-order semantics, mode mutual exclusion, #814 separation, exact-head merge guards, and disabled LIVE boundary.
