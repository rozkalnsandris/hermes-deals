# AUTO-RUN FULL v1 — Hermes Deals source-to-DONE orchestration

Status: PROPOSED until the enabling PR is merged to `main`.
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

Later issue edits may clarify or reduce work but do not silently add authority. New repository scope, mutation classes, secrets, permissions, trust boundaries or live targets cause `STOP_SCOPE_OR_RISK` unless separately authorized by the applicable repository contract.

After a valid receipt, controller #814 becomes the active pointer.

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

- the target issue and activation receipt still match;
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

Three materially identical failed attempts without a materially new safe hypothesis terminate as `STOP_ERROR`. Do not loop the same failed approach indefinitely.

## Scheduled controller

One recurring ChatGPT Plus Scheduled Task may service Hermes Deals AUTO-RUN runs.

Each scheduled run:

1. reads controller #814;
2. if state is `IDLE`, does nothing and does not notify;
3. otherwise reads the exact target issue and activation receipt;
4. refreshes current repository, PR, CI and review state;
5. performs the maximum coherent work allowed by the frozen source envelope;
6. persists state/evidence back to GitHub;
7. never crosses a STRICT live gate without separate explicit owner authorization;
8. notifies only for `DONE`, `PAUSED_OWNER_LIVE_GATE`, `STOP_SCOPE_OR_RISK`, `STOP_ERROR`, or a required platform approval.

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
