# AUTO-RUN FULL v1 — Hermes Deals source-to-DONE orchestration

Status: ACTIVE on `main` since merged PR #816.
Canonical machine contract: `.github/auto-run-full-v1.json`
Enablement issue: `hermes-deals#815`
Durable controller state: `hermes-deals#814`

## Goal

The owner starts one exact issue-scoped run with:

```text
AUTO-RUN FULL hermes-deals #812
```

For a source-only issue, that one command is the up-front owner authorization for the frozen issue's source work and exact converged merge. Automation may then continue through analysis, implementation, tests, branch/PR, CI/review corrections, exact-head merge, post-merge verification, issue completion receipt and `DONE` without routine intermediate owner nudges.

This is not repository-wide blanket authority and it is intentionally stricter than the RPi5_main variant for live work.

## Deals-specific authority split

AUTO-RUN FULL authorizes **source + merge only**.

It does not by itself authorize any Hermes Deals STRICT live class:

- production deploy;
- production database write or migration;
- Review or publication write;
- retained-evidence or source-evidence mutation;
- runtime/replay/APPLY or runtime-executor invocation;
- live collector/source execution with write effects;
- scheduler/systemd/host/container mutation;
- secrets, credentials, permission or trust-boundary changes;
- Cloudflare/DNS/Access/infrastructure mutation;
- arbitrary SSH/sudo/shell authority;
- undeclared retry, rollback or cleanup across a live boundary.

If the issue Definition of Done includes one of those classes, AUTO-RUN may finish and merge the authorized source portion, persist the exact remaining gate, and enter `PAUSED_OWNER_LIVE_GATE`. It must not claim `DONE` until the remaining DoD is actually satisfied under a separate explicit live authorization that follows the repository's existing live contracts.

This split preserves the Hermes Deals rule that merge never implies deploy, DB/Review writes, retained-evidence mutation, runtime activation or infrastructure authority.

## Command routing

The only activation form is:

```text
AUTO-RUN FULL hermes-deals #<positive issue number>
```

The mode is never inferred from:

- `START` or `START hermes-deals`;
- `turpini`;
- controller state;
- a previous AUTO-RUN run;
- prior authorization receipts;
- roadmap/handoff continuity;
- deploy-queue state;
- historical chat or memory.

`turpini` may resume an already-active AUTO-RUN run immediately, but it cannot create or widen authority.

## Durable control plane

GitHub is canonical. Chat/session lifetime is not task lifetime.

The target issue carries the frozen activation receipt and work evidence. Controller issue `#814` carries the single active-task pointer and externally visible state. Every worker reconstructs the run from fresh GitHub state rather than trusting chat history.

Only one Hermes Deals AUTO-RUN issue may be active at a time. Activation fails closed while controller #814 points at another active issue.

## Activation transaction

Before source mutation, the activating worker freshly reads:

1. `AGENTS.md`;
2. `.github/start-mode-routing.json`;
3. `.github/auto-run-full-v1.json`;
4. the exact open target issue;
5. current `main`;
6. overlapping/related PRs, exact CI and review state;
7. relevant dependencies, trackers and handoffs;
8. controller issue `#814`.

Preferred write order is:

1. authorization receipt on the exact target issue;
2. post-receipt current-`main` revalidation;
3. controller #814 activation;
4. source/branch/PR work.

It then writes an owner-identity target-issue comment with schema:

```text
rozkalns.auto-run-full-authorization.v1
```

The receipt freezes at least:

- repository and issue number;
- Definition of Done used for the run;
- allowed source actions;
- merge authority;
- retry semantics;
- explicit exclusions, especially all unapproved STRICT live classes.

The authorization receipt is mandatory before any controller-active pointer write, branch creation, source-file write, commit/push, PR creation/update, merge, runtime or live mutation.

### Harmless pre-receipt metadata recovery

Classification labels or other issue metadata are not required for activation and should normally be left until after the authorization receipt. However, an idempotent **same-target issue metadata write** such as adding a classification label does not by itself consume the owner authorization and does not count as source or live mutation.

If such a metadata-only write occurs before the receipt, the same explicit current AUTO-RUN command may continue only after fresh revalidation proves all of the following:

- controller #814 is still `IDLE` with `active_issue: null`;
- the exact target issue is still open;
- the target issue scope/Definition of Done has not widened;
- no branch, source-file, commit, push, PR, merge, controller-active, runtime or live mutation occurred;
- current `main` and repository rules/policy have been freshly re-read.

The authorization receipt must then be persisted before any non-metadata mutation. A pre-receipt source, branch, PR, merge, controller-active, runtime/live, secret/permission/trust-boundary or cross-repository mutation remains fail-closed and requires STOP/new authorization as applicable.

### Post-receipt `main` stability barrier

An authorization receipt is not usable for source or merge authority merely because its comment write succeeded. The activating worker must establish a **post-receipt `main` stability barrier** before controller `WORKING`, branch creation, source edits, commit/push, PR mutation, merge or runtime/live mutation:

1. freshly read current `main` as `M0` with the normal activation inputs;
2. write the immutable receipt with `activation_main_sha=M0`;
3. immediately fresh-read current `main` as `M1`;
4. use that receipt for source/merge authority only if `M1 == M0`.

If `M1 != M0` and no branch/source/commit/PR/merge/runtime/live mutation has occurred, this is recoverable main-only concurrency drift, not a new owner gate. The worker must preserve the old receipt unchanged, freshly revalidate repository rules, the exact target issue scope, controller ownership, overlapping PR/CI/review state and dependencies, then append a new owner-identity receipt with the identical frozen Definition of Done/actions/merge authority/exclusions plus:

- `supersedes_comment_id`: the immediately prior stale receipt comment id;
- `supersession_reason`: `MAIN_DRIFT_BEFORE_SOURCE`;
- `activation_main_sha`: the newly read current `main` SHA.

The superseding receipt itself must pass the same post-write `main` revalidation. Only the latest receipt whose `activation_main_sha` still equals post-write current `main` is authoritative. Superseded/stale receipts remain immutable audit evidence and must never be deleted or edited.

A new explicit current `AUTO-RUN FULL hermes-deals #<issue>` command may also supersede an unusable stale receipt left by a prior STOP when controller #814 is still `IDLE` (or the same issue is only `PAUSED_EXTERNAL`), the target issue remains open with the same frozen scope, and no source/live mutation occurred. The old STOP receipt remains in history; the new command does not silently reuse it.

Inline stabilization is limited to three consecutive `main` drifts. If `main` still moves, the worker records the same issue as `PAUSED_EXTERNAL` with the latest receipt pointer so the scheduled controller can resume later. That paused pointer is **not source authority**. A later scheduled run must freshly revalidate the same frozen issue and establish a stable superseding receipt before any source/branch/PR/merge work.

This recovery is only for main-only drift before source work. Scope/DoD widening, incompatible repository-rule changes, another active controller issue, trust-boundary changes, or a receipt mismatch discovered after branch/source/PR/merge/runtime/live mutation remain fail-closed and must not be repaired by silent receipt supersession.

Later issue edits may clarify or reduce work but do not silently add authority. New repository scope, mutation classes, secrets, permissions, trust boundaries or live targets cause `STOP_SCOPE_OR_RISK` unless separately authorized by the applicable repository contract.

After a stable receipt, controller #814 becomes the active working pointer. A `PAUSED_EXTERNAL` pointer created only for repeated activation drift is resumability state and grants no source authority until stability is re-established.

## Source convergence loop

While the source portion of the target issue is incomplete, each run makes the maximum coherent progress available:

1. refresh repository rules, target issue, current main and active PR state;
2. inspect current source/evidence and select the smallest coherent change;
3. implement only inside the frozen source envelope;
4. run focused validation first;
5. inspect the exact diff;
6. commit exact intended paths and push;
7. create or update the canonical PR;
8. inspect CI and actionable review findings;
9. correct branch-caused failures or review findings without scope expansion;
10. resolve ordinary merge conflicts without reset/rebase/force/history rewrite;
11. fresh-read exact PR head, current base/main, mergeability and required checks;
12. merge when the frozen source authorization is still satisfied;
13. verify exact post-merge main and exact-main CI;
14. reconcile target Definition of Done;
15. either write `DONE` for a completed source-only task or persist `PAUSED_OWNER_LIVE_GATE` for an outstanding STRICT live gate.

Session end, CI waiting, ordinary CI failure, review findings and ordinary merge conflicts are scheduling/technical states, not owner gates.

## Merge semantics

The explicit AUTO-RUN FULL command is the owner's merge decision for the exact frozen source issue. A second literal `MERGE` message is not required if all of the following are freshly true:

- the target issue and latest stable activation receipt still match;
- the PR is the canonical implementation for the issue;
- the exact current PR head was freshly read;
- required CI/checks pass;
- unresolved actionable review findings are zero;
- the diff remains inside the frozen source envelope;
- no force merge, reset, rebase, force push or history rewrite is required.

A changed head invalidates old readiness evidence and requires fresh CI/review/mergeability inspection, but does not require a new owner message if the new head remains within the same frozen source authorization.

## STRICT live gate

AUTO-RUN FULL never treats a source merge as live authority.

When a target issue requires production/runtime/evidence mutation after source convergence, the controller records the exact remaining class and target and enters:

```text
PAUSED_OWNER_LIVE_GATE
```

The worker may continue read-only/preflight preparation permitted by existing repository contracts, but the first STRICT mutation requires a separate explicit owner authorization under the relevant deploy/runtime/evidence contract.

If a new live class appears that was not part of the target's original declared scope, use `STOP_SCOPE_OR_RISK` instead of inventing a new authority path.

## Controller states

```text
IDLE
ACTIVATING
WORKING
WAITING_CI
WAITING_REVIEW
CORRECTING
WAITING_SCHEDULED_RESUME
PAUSED_USAGE
PAUSED_PLATFORM_APPROVAL
PAUSED_EXTERNAL
PAUSED_OWNER_LIVE_GATE
VERIFYING
DONE
STOP_SCOPE_OR_RISK
STOP_ERROR
```

`PAUSED_PLATFORM_APPROVAL` means ChatGPT/app policy requires a UI approval that repository policy cannot bypass.

Three materially identical failed technical attempts without a materially new safe hypothesis terminate as `STOP_ERROR`. Three consecutive pre-source `main` drifts are different: they enter resumable `PAUSED_EXTERNAL`, because no source authority has yet been exercised.

## Scheduled controller

One recurring ChatGPT Plus Scheduled Task may service Hermes Deals AUTO-RUN runs.

Each scheduled run:

1. reads controller #814;
2. if state is `IDLE`, does nothing and does not notify;
3. otherwise reads the exact target issue and activation receipt chain;
4. if activation is `PAUSED_EXTERNAL` because of receipt/main drift, establishes a latest stable superseding receipt before any source work;
5. refreshes current repository, PR, CI and review state;
6. performs the maximum coherent work allowed by the frozen source envelope;
7. persists state/evidence back to GitHub;
8. never crosses a STRICT live gate without separate explicit owner authorization;
9. notifies only for `DONE`, `PAUSED_OWNER_LIVE_GATE`, `STOP_SCOPE_OR_RISK`, `STOP_ERROR`, or a required platform approval.

## Billing/model constraint

AUTO-RUN FULL is ChatGPT Plus first:

- no provider LLM API key;
- no token-billed model fallback;
- no automatic paid-credit purchase;
- Codex is optional, not required;
- GitHub Copilot is optional, not required.

If usage is temporarily exhausted, persist `PAUSED_USAGE`; do not silently change billing mode.

## Completion

A source-only issue reaches `DONE` only when:

- its frozen Definition of Done is satisfied by current evidence;
- exact merged source and exact-main CI are verified;
- the final GitHub receipt records relevant issue/PR/merge/CI evidence;
- no unresolved actionable review findings remain;
- no undeclared STRICT live work is being pretended complete;
- controller #814 returns to `IDLE`.

The intended first source-only canary after activation is:

```text
AUTO-RUN FULL hermes-deals #812
```

Issue #812 is a fixed five-item same-risk frontend/mobile/accessibility batch and explicitly excludes backend, DB, retailer, runtime, deploy and infrastructure work, making it suitable to prove the source-to-merge-to-DONE loop without crossing a live boundary.
