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

<!-- BEGIN FAST-LANE-V2.1-MANAGED -->
## FAST-LANE v2.1 Hybrid

Hermes Deals adopts the shared FAST/STRICT delivery model in `docs/FAST_LANE_V2_1.md`.

- **FAST** is source-only work with no new trust boundary or live mutation. An explicit owner instruction such as `FAST #702 līdz Ready` may authorize one coherent execution batch from fresh GitHub state through Ready.
- FAST may batch **2-5 closely related same-risk work items** when they form one coherent acceptance story and do not cross a persistence/runtime/production boundary.
- After initial publication, at most **two scope-preserving corrective commits** may address CI/review findings inside the original FAST scope. A third correction or any material scope/risk expansion requires STOP and new authorization.
- Use selective CI by changed-file classification and a stable `FAST-LANE Merge Gate`. Required checks must not depend on a workflow being skipped entirely by top-level path filters.
- Produce one complete Ready receipt. Immediately before merge refresh only mutable evidence: current main/base, exact head, mergeability, CI/checks, reviews/threads, and policy state.
- **STRICT** includes runtime/replay execution, retained-evidence writes, production database writes/migrations, deploy, scheduler/systemd, host/container mutation, secrets/credentials, Cloudflare mutation, scraper/runtime activation, and equivalent live authority.
- Merge remains explicit owner authority. Merge never authorizes deployment, migration or runtime mutation.
- If an authorized live mutation starts and an error or ambiguity occurs, preserve evidence and STOP; do not retry, roll back, clean up or choose an alternate mutation path without new authorization.

Hermes Deals local safety semantics remain stricter where stated. In particular, plain `turpini` remains safe/read-only/source-level and does **not** authorize GitHub writes, merge, deployment or other mutations.
<!-- END FAST-LANE-V2.1-MANAGED -->
