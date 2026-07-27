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
