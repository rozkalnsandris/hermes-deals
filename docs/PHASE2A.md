# Phase 2A — Netto real offer ingestion

Goal: turn the already proven public Netto store HTML source into validated `OfferCandidate` rows without changing the stable Phase-1 contract.

## Flow

1. Fetch the configured Netto store page and save an immutable raw snapshot.
2. Parse only the `Filial-Angebote` section.
3. Convert card text into `OfferCandidate` objects.
4. Validate every candidate with Pydantic.
5. Enforce a minimum-offer safety gate before writing anything.
6. Persist an idempotent batch tied to the raw `snapshot_id`.
7. Expose the newest parsed batch at `/api/v1/offers/latest/netto`.

## Safety rules

- No browser automation and no anti-bot bypass.
- No price is invented when the source is ambiguous.
- A parser result below the minimum gate is treated as a parser failure and is not written.
- Raw source lines are kept in `raw_payload` for audit/debugging.
- Re-running the same snapshot replaces only rows for that snapshot.
- Other retailer probes remain independent.

## Deliberate Phase 2A limitations

- The configured store `6071` remains a technical Dortmund sample until the family's actual branch is confirmed.
- Valid-from/valid-until are not inferred yet because the visible store-card section does not attach a trustworthy date to each individual card.
- Brand extraction is intentionally deferred; guessing a brand from the first word would create bad canonical data.
- Product normalization/cross-store matching comes after at least two real retailer parsers exist.


## v0.2.1 deploy hardening

- Worker runs with the host UID/GID for bind-mounted raw snapshots.
- Deployment recovery preserves raw snapshots and restores the last Phase 1 baseline safely.
- Final API verification avoids shell-escaped f-string expressions.


## v0.2.2 deploy hardening
- Final summary no longer depends on unset shell env variables.
- Successful functional verification is the deploy commit point; cosmetic output cannot trigger rollback.
- Public bind endpoint is read from `docker compose port web 80`.
