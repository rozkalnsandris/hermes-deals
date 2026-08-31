<!-- BEGIN HERMES-DEALS-CODEX-MANAGED -->
## Hermes Deals working agreements

- This repository is the self-built Hermes Deals grocery-deals system. Do not replace it with KitchenOwl, Mealie, Bring, KaufDA, MeinProspekt, or another aggregator/product.
- Priority retailers are Lidl and Netto Marken-Discount; ALDI Nord and EDEKA remain supported comparison sources.
- Work evidence-first: inspect current code, current Git diff/status, latest relevant runtime evidence, and tests before proposing a change.
- Keep facts, hypotheses, and assumptions separate. Never claim a retailer/source problem is solved without fresh runtime/log evidence.
- Preserve immutable source observations and provenance. A parsed offer must remain traceable to the source snapshot/observation that produced it.
- Do not fabricate offers, prices, validity, store identity, region identity, or product mappings to make tests pass.
- Treat retailer store, region/warehouse, zone, URL parameters, cookies/localStorage, and server responses as separate evidence. In particular, do not infer a Lidl branch from a numeric region id alone and do not hard-code a store/region binding without source evidence.
- Prefer the smallest coherent fix. Do not perform broad rewrites or file splitting merely because a file is large; refactor only when it improves a verified boundary and preserves behavior with tests.
- Before schema or persistence changes, inspect the current Alembic head and persistence invariants. Never edit an already-applied migration in place.
- Production writes/deploys require an explicit task, a pre-change snapshot/audit, targeted verification, and a post-change canary. Never use destructive cleanup as a shortcut.
- Run focused tests for the changed area first. At a release/deploy gate, run the repository's established full regression suite and report exact pass/fail counts.
- When browser/source investigation is needed, prefer Playwright CLI because it is context-efficient. Use a named/persistent session when cookies or store-selection state matter; inspect requests, cookies, localStorage/sessionStorage, redirects, and final rendered state.
- Save temporary browser traces/snapshots under `.codex/evidence/`; do not commit session secrets or authenticated storage state.
- Finish each task with: changed files, commands/tests run, evidence observed, unresolved uncertainty, and the next smallest safe step.
- Use the `hermes-deals` skill for retailer-source audits, parser changes, persistence changes, production gates, and B15/B15B Lidl work.
<!-- END HERMES-DEALS-CODEX-MANAGED -->

## Startup command routing

Read `.github/start-mode-routing.json` before selecting a startup/continuation mode.

- Bare `START`, `START hermes-deals`, `turpini`, or equivalent continuation means normal **FAST-LANE v2.2**. It is not `GITHUB-ONLY`, `LIVE-ALL`, or `AUTO-RUN FULL`.
- Activate `GITHUB-ONLY` only when the owner explicitly includes `GITHUB-ONLY` (or the documented `git hub only` spelling) in the current command.
- Activate `LIVE-ALL` only when the owner explicitly includes `LIVE-ALL` in the current command.
- Activate `AUTO-RUN FULL` only from the exact explicit form `AUTO-RUN FULL hermes-deals #<positive issue number>` and then read `.github/auto-run-full-v1.json`.
- Never infer an explicit mode from `.github/start-github-only.json`, deploy-queue state, handoff/issue continuity, executor availability, historical chat mode, controller state, or a prior authorization receipt.
- Continuity evidence may affect lane selection only after command mode has been selected; it must never rewrite the command mode itself.

<!-- BEGIN AUTO-RUN-FULL-V1-MANAGED -->
## AUTO-RUN FULL v1 — Hermes Deals

Canonical machine contract: `.github/auto-run-full-v1.json`. Durable controller: issue `#814`.

`AUTO-RUN FULL hermes-deals #<issue>` is one explicit issue-specific owner decision for **source work plus merge** inside the target issue's frozen Definition of Done. It is not repository-wide blanket authority.

Activation must freshly read repository rules, routing/policy, the exact open target issue, current `main`, overlapping PR/CI/review state, relevant dependencies, and controller #814. It must persist an owner-identity `rozkalns.auto-run-full-authorization.v1` receipt on the target issue before source mutation. The receipt freezes the issue DoD, source actions, merge authority, retry semantics, and explicit exclusions; later issue edits cannot silently widen authority.

Within that frozen source envelope, routine source analysis, branch/commit/push, PR creation/update, CI waiting/inspection, review ingestion, scope-preserving corrections, ordinary merge-conflict correction, exact-head merge, post-merge read-only verification, and final GitHub receipts are technical steps and do not require another owner nudge. The explicit AUTO-RUN FULL command is the merge authorization for that exact frozen source task when fresh exact-head CI/review/mergeability checks pass. Force merge, reset, rebase, force-push, or history rewrite are forbidden.

Hermes Deals STRICT live boundaries remain separately explicit. AUTO-RUN FULL by itself does **not** authorize production deploy, production DB write/migration, Review/publication write, retained/source-evidence mutation, runtime/replay/APPLY execution, live collector/source execution with write effects, scheduler/systemd/host/container mutation, secrets/credentials/permission or trust-boundary changes, Cloudflare/DNS/Access/infrastructure mutation, or arbitrary SSH/sudo/shell authority. If the issue DoD requires such a class, source work may converge and merge, then controller state becomes `PAUSED_OWNER_LIVE_GATE` until the repository's separate exact live authorization is provided.

Only one Hermes Deals AUTO-RUN issue may be active at a time. `turpini` is resume-only for an already-active run and never creates or broadens authority. Session ending, CI waiting/failure, review findings, and ordinary merge conflicts are not owner gates. Platform-required connected-app approval is persisted as `PAUSED_PLATFORM_APPROVAL`. Three materially identical failed attempts without a new safe hypothesis terminate as `STOP_ERROR`.

No provider LLM API key, token-billed fallback, automatic paid-credit purchase, Codex requirement, or Copilot requirement is allowed by this mode.
<!-- END AUTO-RUN-FULL-V1-MANAGED -->

<!-- BEGIN FAST-LANE-V2.2-MANAGED -->
## FAST-LANE v2.2 Composite

Read `docs/FAST_LANE_V2_2.md` as the active local startup contract.

**Primary rule:** the human approves the **RISK / DECISION**; automation executes the **TECHNICAL STEPS**.

- `START`, `turpini`, or equivalent continuation may carry safe source-only work from fresh canonical GitHub state through branch, implementation, focused tests, commit/push, Draft PR, CI/review and up to two scope-preserving corrections until Ready.
- FAST may batch **2-5 closely related same-risk work items** when they form one coherent acceptance story and do not cross a persistence/runtime/production boundary.
- Use selective CI by changed-file classification and a stable `FAST-LANE Merge Gate`. Required checks must not depend on a workflow being skipped entirely by top-level path filters.
- Normal FAST delivery has at most two owner gates: explicit **MERGE**, then one bounded **COMPOSITE LIVE** only when a live mutation is actually required. A valid explicit AUTO-RUN FULL command is a separate mode and does not change bare FAST semantics.
- CI polling, diff inspection, GET/preflight, evidence refresh, checkout discovery, build preparation, candidate verification and reconciliation are technical automation steps, not owner gates.
- Composite Live must bind exact Git SHA, exact target, allowed mutation categories, practical limits, explicit exclusions and expected baseline. Revalidate immediately before the first live write and STOP on drift.
- Authorization is consumed at the first authorized mutation. Any later error, ambiguity or drift requires evidence preservation and STOP; no automatic retry, rollback, cleanup, reset, rebase or alternate mutation path unless explicitly pre-authorized.
- **STRICT** includes runtime/replay execution, retained-evidence writes, production database writes/migrations, deploy, scheduler/systemd, host/container mutation, secrets/credentials, Cloudflare mutation, scraper/runtime activation, and equivalent live authority.
- Produce one complete Ready receipt and one final live receipt when live mutation occurs. Put any remaining owner decision visibly at the end under `ACTION REQUIRED` with exact copyable input when needed.
- Normal FAST merge remains explicit owner authority. Merge never authorizes deployment, migration or runtime mutation.

Hermes Deals local safety semantics remain stricter where stated.
<!-- END FAST-LANE-V2.2-MANAGED -->

<!-- BEGIN GITHUB-ONLY-LIVE-ALL-V1-MANAGED -->
## GITHUB-ONLY / LIVE-ALL v1

Canonical shared contract: `rozkalnsandris/ops-workflows/docs/GITHUB_ONLY_LIVE_ALL.md` with machine invariants in `policy/github-only-live-all-v1.json`.

- `GITHUB-ONLY` (including `git hub only`) means fresh canonical GitHub state, safe source/test/docs work, and rollout preparation up to but not including the first production/runtime/live mutation.
- Persist deferred rollout state as public-safe `[DEPLOY-QUEUE]` issues in `rozkalnsandris/ops-workflows`; chat or memory is never the queue.
- Merge remains separately explicit. Neither `GITHUB-ONLY` nor `LIVE-ALL` authorizes merge.
- A GitHub write whose deterministic side effect runs a production/runtime mutation counts as live work and must not run under `GITHUB-ONLY`.
- Queue `READY` requires the final exact deployable SHA, exact target/entrypoint/preflight/verification/allowed mutations and no outstanding separate prerequisite owner gate.
- `LIVE-ALL` snapshots only open `READY` items present at command start, freshly revalidates exact SHA/target/baseline and may execute only ordinary predeclared rollout mutations that this repository already permits inside the exact authorization envelope.
- Runtime/replay execution, retained-evidence writes, production DB writes/migrations, scheduler/systemd, host/container mutation beyond the exact reviewed rollout, secrets/credentials, Cloudflare infrastructure mutation and scraper/runtime activation remain separately gated where the repository-local contract requires it.
- After any selected live mutation starts, error/ambiguity requires public-safe evidence preservation and STOP of the remaining batch; no automatic retry/rollback/cleanup/reset/rebase/alternate mutation path unless explicitly pre-authorized.
- Hermes Deals local persistence/runtime/production safety semantics remain authoritative and stricter where applicable.
<!-- END GITHUB-ONLY-LIVE-ALL-V1-MANAGED -->

<!-- BEGIN START-GITHUB-ONLY-V1-MANAGED -->
## START_GITHUB_ONLY_V1 deterministic bootstrap amendment

Startup contract: `rozkalnsandris/ops-workflows/docs/START_GITHUB_ONLY_V1.md`.
Repository manifest: `.github/start-github-only.json`.

- `START <repository> GITHUB-ONLY` refreshes local rules/handoff, the pinned shared policy and START contract, current default branch/governance capability, active PRs, active issues/dependencies, and relevant deploy-queue items before selecting the manifest-defined canonical lane.
- Revalidate mutable GitHub state immediately before every state-dependent write.
- The absence of an open issue alone is NOT a STOP condition. Do not invent speculative work.
- If declared tie-breakers cannot resolve equally authoritative lanes, report `AMBIGUOUS_CANONICAL_LANE` instead of choosing arbitrarily.
- Final routing is one of `READY_FOR_MERGE`, `PARKED`, `STOP_ERROR`, `NEW_SCOPE_OR_RISK`, `AMBIGUOUS_CANONICAL_LANE`, or `IDLE`.
- `PARKED` is session-only. **EXECUTOR** availability is session capability, not **READY** rollout eligibility.
- Executor unavailability alone must not change `READY` to `BLOCKED`; use `BLOCKED` only for rollout eligibility or contract failure.
- Repository-local stricter persistence, runtime, production and evidence rules remain authoritative.
<!-- END START-GITHUB-ONLY-V1-MANAGED -->
