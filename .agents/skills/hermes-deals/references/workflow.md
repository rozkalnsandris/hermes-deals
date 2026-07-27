# Hermes Deals gate checklist

## Source / parser gate

- Identify exact immutable input or reproducible live request.
- Record retailer/store scope separately from region/warehouse/zone scope.
- Confirm parser denominator and skip reasons.
- Verify stable source_offer_id / persistence key behavior.
- Replay the same evidence twice and confirm deterministic output.

## Persistence gate

- Inspect current Alembic head and relevant unique constraints.
- Preserve INSERT / ON CONFLICT / immutable replay semantics.
- Test identical replay, divergent replay rejection, and rollback/atomicity where the changed path touches them.
- Do not delete production rows to make a replay succeed.

## Production gate

- Capture pre-change health and counts.
- Apply one controlled change.
- Run targeted canary.
- Capture post-change health, counts, source snapshot identity/hash where applicable, and API read-path output.
- Roll back when invariants fail; do not patch around bad evidence.

## Browser evidence gate

Use Playwright CLI for high-throughput investigation. Inspect `requests`, `request <id>`, cookies, localStorage/sessionStorage, redirects, and final UI state. Use a persistent named session only when state continuity is part of the question. Save non-secret disposable output under `.codex/evidence/`.
