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

<!-- BEGIN FAST-LANE-V2.2-MANAGED -->
## FAST-LANE v2.2 Composite

Read `docs/FAST_LANE_V2_2.md` as the active local startup contract.

**Primary rule:** the human approves the **RISK / DECISION**; automation executes the **TECHNICAL STEPS**.

- `START`, `turpini`, or equivalent continuation may carry safe source-only work from fresh canonical GitHub state through branch, implementation, focused tests, commit/push, Draft PR, CI/review and up to two scope-preserving corrections until Ready.
- FAST may batch **2-5 closely related same-risk work items** when they form one coherent acceptance story and do not cross a persistence/runtime/production boundary.
- Use selective CI by changed-file classification and a stable `FAST-LANE Merge Gate`. Required checks must not depend on a workflow being skipped entirely by top-level path filters.
- Normal delivery has at most two owner gates: explicit **MERGE**, then one bounded **COMPOSITE LIVE** only when a live mutation is actually required.
- CI polling, diff inspection, GET/preflight, evidence refresh, checkout discovery, build preparation, candidate verification and reconciliation are technical automation steps, not owner gates.
- Composite Live must bind exact Git SHA, exact target, allowed mutation categories, practical limits, explicit exclusions and expected baseline. Revalidate immediately before the first live write and STOP on drift.
- Authorization is consumed at the first authorized mutation. Any later error, ambiguity or drift requires evidence preservation and STOP; no automatic retry, rollback, cleanup, reset, rebase or alternate mutation path unless explicitly pre-authorized.
- **STRICT** includes runtime/replay execution, retained-evidence writes, production database writes/migrations, deploy, scheduler/systemd, host/container mutation, secrets/credentials, Cloudflare mutation, scraper/runtime activation, and equivalent live authority.
- Produce one complete Ready receipt and one final live receipt when live mutation occurs. Put any remaining owner decision visibly at the end under `ACTION REQUIRED` with exact copyable input when needed.
- Merge remains explicit owner authority. Merge never authorizes deployment, migration or runtime mutation.

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
