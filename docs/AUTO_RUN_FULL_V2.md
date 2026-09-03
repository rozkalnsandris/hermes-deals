# AUTO-RUN FULL v2 — Hermes Deals event-driven source-to-DONE orchestration

Status: PROPOSED until this policy PR is merged and repository/platform setup gates are completed.
Canonical machine contract: `.github/auto-run-full-v2.json`
Durable controller state: `hermes-deals#814`
Cross-repository rollout: `RPi5_main#315`

## Operating model

`AUTO-RUN FULL` is the normal implementation lane. `FAST-LANE v2.2` remains the safe discovery, audit and non-FULL continuation lane.

Start one exact source implementation run with:

```text
AUTO-RUN FULL hermes-deals #<issue>
```

For the frozen issue, that command authorizes source work plus the exact converged merge. The intended flow is:

```text
source -> PR -> CI -> corrections/review convergence -> guarded auto-merge -> post-merge verification -> DONE
                                                                                                      \
                                                                                                       -> pending-LIVE receipt -> controller IDLE
```

A pending STRICT LIVE gate may keep the target issue open in `PAUSED_OWNER_LIVE_GATE`, but after the source/merge envelope is fully complete and the pending-LIVE receipt is persisted it no longer occupies the single AUTO-RUN source-controller slot.

The command never becomes blanket repository authority and is never inferred from `START`, `turpini`, controller state, prior receipts, chat history or memory.

## FAST-LANE relationship

Bare `START hermes-deals`, `START`, `turpini` or equivalent continuation remains FAST-LANE. Use FAST for discovery, audits, diagnosis, scope/DoD definition and safe work that should stop at a decision boundary.

Once a concrete implementation issue has a usable Definition of Done, prefer `AUTO-RUN FULL hermes-deals #<issue>` rather than repeatedly driving ordinary implementation with `turpini`.

FAST never inherits or infers FULL merge authority.

## Hermes Deals authority split

AUTO-RUN FULL authorizes **source + merge only**.

It does not authorize any STRICT live class, including:

- production deploy;
- production database write/migration;
- Review/publication write;
- retained/source-evidence mutation;
- runtime/replay/APPLY or runtime executor invocation;
- live collector/source execution with write effects;
- scheduler/systemd/host/container mutation;
- secrets/credentials/permission/trust-boundary change;
- Cloudflare/DNS/Access/infrastructure mutation;
- arbitrary SSH/sudo/shell authority;
- undeclared live retry/rollback/cleanup.

If the source portion converges but the issue still has an unapproved STRICT continuation, preserve that exact owner gate in an immutable/public-safe pending-LIVE receipt. The target issue remains `PAUSED_OWNER_LIVE_GATE`, but controller #814 may return to `IDLE` after the source handoff predicates below are satisfied. Returning the controller to `IDLE` does not close, consume, imply, transfer or supersede the LIVE gate. Merge never implies deploy/runtime/DB/Review/evidence authority.

## Pending LIVE handoff and source-controller release

The single active controller slot owns **AUTO-RUN source orchestration**, not an indefinitely pending separate LIVE decision.

Use pending-LIVE receipt schema:

```text
rozkalns.auto-run-pending-live.v1
```

Before controller #814 may release a source-complete issue with STRICT LIVE still pending, all of the following must be freshly true:

- the frozen source Definition of Done has converged;
- the canonical PR is merged;
- exact post-merge `main` is verified;
- relevant exact-main CI is verified;
- unresolved actionable review findings are zero;
- the exact remaining STRICT owner gate is identified;
- the pending-LIVE receipt has been persisted on the target issue.

The receipt must preserve at minimum:

- repository;
- target issue;
- merged `main` SHA;
- canonical PR;
- activation/authorization receipt identity;
- exact remaining owner gate;
- `live_authority_granted: false`.

After the valid receipt is persisted, controller #814 may become `IDLE` with `active_issue: null`. The target issue may remain open in `PAUSED_OWNER_LIVE_GATE`; that status is a backlog/continuation fact, not source-controller ownership.

Controller release is forbidden if the source Definition of Done is incomplete, the canonical PR is not merged, post-merge verification is incomplete, required CI is unresolved/failed, actionable review findings remain, the remaining mutation class is ambiguous, or the pending-LIVE receipt is missing/invalid.

A later LIVE action must enter through the repository's normal fresh explicit LIVE authorization path and freshly bind the then-current source/runtime evidence and permitted mutation envelope. The old AUTO-RUN command, the pending-LIVE receipt, `turpini`, watchdog/event resume, controller state, historical authorization receipts and chat history are not LIVE authority and cannot infer a new AUTO-RUN FULL source authorization.

Releasing a pending-LIVE issue does not weaken the invariant that only one AUTO-RUN **source** issue may be active at once. A different source issue can activate only from a fresh explicit `AUTO-RUN FULL hermes-deals #<issue>` command.

## Durable state and resume architecture

GitHub is canonical. The target issue, activation receipt chain, controller #814, canonical PR and current CI/review state are re-read before state-dependent work.

V2 uses two resume paths:

1. **Primary: GitHub event-triggered ChatGPT Work** for supported PR events such as PR open/ready, review/comment, commit update and completed merge.
2. **Fallback: hourly `Deals AUTO-RUN` Scheduled watchdog** that reconstructs the already-active frozen issue from GitHub.

Event-triggered Work is a latency accelerator, not a new authority source. If unavailable, the watchdog or manual `turpini` resumes the same durable job.

## Activation and main-stability barrier

Before source mutation, freshly read repository rules, routing/v2 policy, exact target issue, current `main`, overlapping PR/CI/review state, relevant dependencies and controller #814.

Preferred write order remains:

1. owner-identity authorization receipt;
2. immediate post-receipt `main` revalidation;
3. controller activation;
4. source work.

Use receipt schema:

```text
rozkalns.auto-run-full-authorization.v2
```

The receipt freezes the issue Definition of Done, allowed source actions, merge authority, retry semantics and explicit exclusions.

The existing main-stability rule remains: bind the receipt to `M0`, write it, fresh-read `M1`, and require `M1 == M0` before source authority becomes usable. Main-only drift before source may be recovered with same-scope immutable superseding receipts; after three consecutive stabilization failures use `PAUSED_EXTERNAL`. Scope/rule/trust-boundary drift remains fail-closed.

## Source convergence loop

Within the stable frozen source envelope:

1. refresh current GitHub state;
2. implement the smallest coherent source change;
3. run focused validation and inspect exact diff;
4. commit exact paths and push;
5. create/update the canonical PR;
6. inspect CI and actionable review findings;
7. apply scope-preserving corrections;
8. resolve ordinary merge conflicts without reset/rebase/force/history rewrite;
9. repeat until exact-head source/review/CI convergence;
10. perform final exact-head merge readiness;
11. prefer GitHub native auto-merge when repository capability is enabled;
12. verify exact post-merge main and relevant exact-main CI;
13. reconcile the frozen source Definition of Done;
14. finish as `DONE` for completed source-only scope, or persist a valid pending-LIVE receipt when a separate STRICT gate remains;
15. after a valid pending-LIVE handoff, keep the target issue's STRICT continuation visible while returning controller #814 to `IDLE` with no active source issue.

Three materially identical technical failures without a materially new safe hypothesis produce `STOP_ERROR`.

## Guarded GitHub auto-merge

V2 does **not** arm auto-merge early on an unreviewed or mutable head.

Before enabling auto-merge, all of the following must be freshly true for the exact current PR head:

- target issue and latest stable authorization receipt still match;
- the PR is the canonical implementation;
- exact head SHA is freshly read;
- final diff/scope review is complete;
- required CI/checks pass;
- unresolved actionable review findings are zero;
- current mergeability is acceptable;
- diff remains within the frozen source envelope;
- repository ruleset requirements are satisfied;
- no force/history rewrite is required.

Only then may the worker enable GitHub native auto-merge on that exact canonical PR. A changed head voids old readiness and requires fresh review/checks before auto-merge may be enabled again.

If repository auto-merge capability is unavailable, direct exact-head merge remains a fallback only after the same final readiness gate and only because the explicit FULL command already supplies merge authority for that frozen source task.

GitHub repository `Allow auto-merge` must be enabled before per-PR auto-merge can be used. The connected ChatGPT GitHub app does not currently expose repository-administration settings, so this is a separate setup gate and must not weaken the existing `Protect main` ruleset.

## Controller states

```text
IDLE
ACTIVATING
WORKING
WAITING_CI
WAITING_REVIEW
CORRECTING
WAITING_EVENT_RESUME
WAITING_WATCHDOG_RESUME
PAUSED_USAGE
PAUSED_PLATFORM_APPROVAL
PAUSED_EXTERNAL
PAUSED_OWNER_LIVE_GATE
VERIFYING
DONE
STOP_SCOPE_OR_RISK
STOP_ERROR
```

`PAUSED_OWNER_LIVE_GATE` may describe the target issue's remaining continuation after source orchestration has been handed off. It does not require controller #814 to retain `active_issue` once the pending-LIVE release contract is satisfied.

Session ending, CI waiting/failure, review findings and ordinary merge conflicts are technical/resume states, not new owner gates.

## Billing/model boundary

AUTO-RUN FULL remains ChatGPT Plus first:

- no provider LLM API keys;
- no token-billed fallback;
- no automatic paid-credit purchase;
- Codex and Copilot are optional, not correctness dependencies.

If product usage is exhausted, persist `PAUSED_USAGE`; do not silently change billing mode.

## Completion

A source-only task reaches `DONE` only when its frozen Definition of Done is satisfied by current evidence, exact merged source/post-merge main are verified, relevant exact-main CI is verified, unresolved actionable review findings are zero, the final GitHub receipt is written and controller #814 returns to `IDLE`.

If STRICT live work remains, the overall target issue is not falsely marked `DONE`. Instead, after source/merge convergence and a valid `rozkalns.auto-run-pending-live.v1` receipt, source-controller occupancy may end: controller #814 returns to `IDLE` with `active_issue: null`, while the target issue remains open with the exact `PAUSED_OWNER_LIVE_GATE` continuation. A later LIVE operation still requires a fresh explicit owner authorization and fresh then-current evidence binding.
