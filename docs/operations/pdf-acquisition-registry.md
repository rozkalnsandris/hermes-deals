# PDF acquisition registry

Tracking: [#1069](https://github.com/rozkalnsandris/hermes-deals/issues/1069).
This is a source-only foundation after the read-only
[storage inventory](pdf-retention-inventory.md). It does not activate collectors,
run a production migration, enforce physical deletion, or verify deployed storage.

## One table, two operations

`pdf_acquisitions` contains immutable observations identified by
`(pdf_sha256, evidence_ref)`, with `acquired_at` and `recorded_at`.
The SHA is the binary PDF identity, not the retailer, filename or URL.
`evidence_ref` identifies verified acquisition evidence, for example a specific
immutable manifest hash and PDF field. The caller must verify the evidence; this
metadata module does not read files or establish trust in supplied timestamps.

`register_pdf_acquisition(session, ...)` inserts an observation or returns false
for an exact replay. Repeating the same reference with a different acquisition
date, including changing an unknown date to a known one, raises a conflict.
A newer recording time does not change the original row. The PostgreSQL/SQLite
unique key and conflict-safe insert make identical concurrent submissions
idempotent. The service has no update/delete operation and does not commit.
These are service invariants; privileged direct SQL is not blocked by triggers.

`pdf_retention(session, sha, as_of=...)` computes the earliest observed time.
The deadline is exactly 30 × 24 elapsed hours later, in UTC. There is no separately
stored expiry date to drift or renew. A later observation adds evidence without
extending the deadline; an earlier proven observation shortens it. No implicit
wall clock is used: acquisition, recording and evaluation timestamps must have
timezones. Acquisition cannot follow recording.

| State | Meaning |
| --- | --- |
| `unregistered` | No observations for that content; no permission to retain/serve is implied. |
| `acquisition_unknown` | At least one observation has an unresolved acquisition age. A later download cannot reset it. |
| `not_yet_acquired` | Evaluation precedes the earliest known acquisition. |
| `within_retention` | All registered observations have known dates and the deadline has not arrived; this does not verify bytes or complete storage coverage. |
| `raw_expired` | The known deadline has arrived; this is a deadline state, not proof of physical deletion. |

If unknown-age evidence exists, `first_acquired_at` remains null. A dated
observation can still establish an upper bound `expires_at`: before that bound
the state stays unknown, and at/after it the state is expired. Unknown evidence
cannot make already expired bytes usable again. Resolving unknown historical
observations needs a separately reviewed reconciliation operation; this API
deliberately cannot rewrite them.

## Schema and activation boundary

Additive Alembic revision `0009_pdf_acquisitions` follows
`0008_household_state`. It creates one empty table. No backfill infers dates from
mtime/ctime, retailer publication time, ZIP upload time or current time.
SourceSnapshot, offers, prices and product links are not modified.

No existing collector, API endpoint, preview reader or scheduler calls this module
yet. The normal image CMD starts Uvicorn, not Alembic. CI applies the new migration
only to isolated test databases. Production schema rollout and writer/reader
integration still require their own validated steps. Do not enable a writer with
an empty registry and assume existing PDF content is newly acquired.

## Remaining integration

- [ ] Reconcile physical inventory and prove earliest acquisition across raw,
  staging, corpus, CI archives and backups; import unknown ages as unknown.
- [ ] Apply the reviewed additive migration to the intended environment.
- [ ] Bind official-source metadata and file-copy/derived-preview locations to
  the content identity without conflating retailer/store/product identity.
- [ ] Register verified acquisition before publishing new bytes; writer and reader
  must deny unknown, unregistered and expired identities. Coordinate concurrent
  admission and cleanup before activation; a read here is not a filesystem lock.
- [ ] Connect Netto first through its existing PDF writer; preserve its HTML
  primary path. Adapt Lidl corpus/replay last.
- [ ] Append per-copy deletion receipts only after verified physical outcomes.
  Keep the acquisition observations after deletion so redownload cannot renew TTL.
- [ ] Implement bounded dry-run/apply cleanup and backup/archive deadlines no later
  than the original 30-day limit. Keep price history and immutable observations.
- [ ] Reconcile historical long-lived held-out retention contracts.

Validation includes 29/30/31-day and exact-deadline boundaries, DST, duplicate and
earlier observations, unknown ages, conflicting references, caller rollback,
additive migration preservation and concurrent registration on PostgreSQL 18.
