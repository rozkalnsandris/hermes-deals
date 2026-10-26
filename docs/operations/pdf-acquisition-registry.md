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

The Netto store-prospect collector and its existing bundle writer now accept an
explicit `pdf_registry_engine` argument. No CLI, scheduled job or existing caller
supplies it by default. Store-prospect replay also accepts an explicit registry
connection (see below); API/preview readers remain unwired. The normal image CMD
starts Uvicorn, not Alembic. CI applies migrations only to isolated test databases.
Production schema rollout and integration activation require their own validated
steps. Do not enable a writer with an empty registry and assume existing PDF
content is newly acquired.

## Remaining integration

- [ ] Reconcile physical inventory and prove earliest acquisition across raw,
  staging, corpus, CI archives and backups; import unknown ages as unknown.
- [ ] Apply the reviewed additive migration to the intended environment.
- [ ] Bind official-source metadata and file-copy/derived-preview locations to
  the content identity without conflating retailer/store/product identity.
- [ ] Register verified acquisition before publishing new bytes; writer and reader
  must deny unknown, unregistered and expired identities. Coordinate concurrent
  admission and cleanup before activation; a read here is not a filesystem lock.
- [x] Prepare an explicit registry connection in Netto's existing PDF writer and
  store-prospect collector; preserve the default capture and HTML primary paths.
- [ ] Activate Netto only after the prerequisites below. Adapt Lidl corpus/replay last.
- [ ] Append per-copy deletion receipts only after verified physical outcomes.
  Keep the acquisition observations after deletion so redownload cannot renew TTL.
- [ ] Implement bounded dry-run/apply cleanup and backup/archive deadlines no later
  than the original 30-day limit. Keep price history and immutable observations.
- [ ] Reconcile historical long-lived held-out retention contracts.

Validation includes 29/30/31-day and exact-deadline boundaries, DST, duplicate and
earlier observations, unknown ages, conflicting references, caller rollback,
additive migration preservation and concurrent registration on PostgreSQL 18.

## Explicit Netto writer connection (not activated)

`_write_bundle(..., pdf_registry_engine=engine)` and
`collect_netto_store_prospect(..., pdf_registry_engine=engine)` use the same
shared acquisition table. This is an argument, not a new collector, environment
switch, database or scheduler. Omission preserves the legacy capture path and
does not query the new table; this legacy mode does **not** enforce retention.

With the argument supplied, the existing writer validates the PDF and computes
the unchanged V3 manifest before file I/O. It records the observation in an owned,
separate Session and commits before writing any bundle file. A later file error
or caller rollback cannot erase that acquisition. The evidence reference binds
the computed manifest SHA and PDF field. A failed write can leave an acquisition
without a published manifest: it records acquired bytes, not proof of publication.
The source URL, store and paths remain in the manifest when publication succeeds.

The collector's existing `collected_at` is captured before the network fetch,
so it is a conservative acquisition bound. Direct callers must provide an aware,
verified acquisition time, never a replay/import time. The admission check uses
the current UTC wall clock, not that historical timestamp. A later observation
cannot extend a known deadline. Unknown/expired content is denied before any
bundle files are written. An unregistered PDF already present at the destination
(including a dangling symlink) is denied for reconciliation instead of assigned
today's age. Registry/schema/commit errors never fall back to unguarded writing.

This local check cannot discover the same content under another name, root or
archive. Activation requires the full existing-copy inventory and reconciliation
in the **shared** registry; a fresh per-run database is not acceptable. The
registry engine must provide an independent connection, not the caller's active
Connection or a shared single-connection transaction. No schema is created here.

Admission alone is not the complete 30-day lifecycle: it does not lock concurrent
historical reconciliation/cleanup against filesystem publication, remove existing
copies, or prevent a slow write from crossing a deadline. Keep this connection
disarmed until coordinated publication/cleanup, reader expiry and a deletion
schedule with reserve before the deadline are validated. Weekly/held-out capture
callers remain on the legacy path pending that same integration; they are not
silently connected to a production database.

CI runs the new admission tests with real synthetic PDFs/files and separate
database transactions on both SQLite and the migrated PostgreSQL 18 service.
They cover replay/renaming, exact expiry, unknown/pre-existing copies, failed
writes and commits, missing schema, invalid timestamps, collector denial and
unchanged V3/default behavior. They make no live-retailer or storage-coverage claim.

## Explicit Netto replay connection (not activated)

`parse_netto_store_prospect_snapshot(..., pdf_registry_engine=engine)` checks
the shared registry before opening PDF bytes. V3 always requires its PDF; older
manifests require it when validity comes from PDF text. Those paths now share one
PDF read and SHA verification, so V3/PDF validity no longer reads the file twice.
The existing PDF format, source/store and date-consistency checks remain.

Only `within_retention` proceeds. The evaluation uses current UTC time, never
the historical parser context date. Other states raise `PdfRetentionDenied`,
whose `retention` attribute exposes the content SHA, state and available deadline.
For expired content this yields `raw_expired` even if the PDF was already
removed. It is neither a successful full replay nor a deletion/corruption receipt.
For content still within its term, missing files and SHA mismatches retain their
ordinary errors. Registry errors do not fall back to PDF access.

Legacy HTML-only V1/V2 manifests require neither PDF nor registry. The separate
HTML-primary collector/replay and persisted prices remain independent of PDF
availability. Tests preserve a stored price and its SourceSnapshot after an
expired, missing PDF is refused; a full replay cannot manufacture new offers.

Omitting the argument keeps legacy replay behavior. No production/API/CLI caller
is activated by this change. Daily-special HTTP/weekly activation, preview readers, physical-copy inventory,
coordinated read/write/cleanup and deadline enforcement during long operations
remain separate TODOs. The exception is the
typed boundary for a future caller; this change does not add a UI status or change
the existing Offers page.


## Explicit Netto daily-special cache connection (not activated)

`read_netto_daily_specials(snapshot, pdf_registry_engine=engine)` wraps the
existing daily-special parser/cache in the same module. It verifies the successful
Netto family snapshot identity and immutable manifest SHA on every call, then
checks the shared acquisition registry outside `lru_cache`. A warmed cache,
including one populated by a legacy caller, cannot bypass the current deadline.
The check uses UTC wall time, independent of the requested offer date or historical
snapshot date, both before the cache call and after potentially slow parsing.

Expired, unknown-age, unregistered or not-yet-acquired content raises the existing
`PdfRetentionDenied`; registry failures propagate. Neither case becomes an empty
successful replay. Explicit HTML-only legacy manifests return no PDF-derived daily
offers without querying the registry; missing required V3 metadata is an error.
Cold reads retain existing PDF/publication integrity errors. The cache contains
structured offers, not PDF bytes: a warm result within retention does not prove
that the original PDF still exists. Denial does not erase persisted price history.

HTTP `daily_specials` and the weekly view still use the unchanged legacy entry.
This explicit function is source preparation, not an activated 30-day policy or a
new UI status. No PDF files, registry rows or production configuration are changed
by adding it. The before/after checks do not lock cleanup or reconciliation against
a read, and do not physically interrupt a parser at the deadline. Activation still
requires the shared inventory, migration and coordinated lifecycle prerequisites.

CI exercises real manifests/PDF files and SQLite plus migrated PostgreSQL, with a
synthetic daily parser result to isolate the cache boundary. Tests cover warmed
cache expiry, unknown ages, manifest tampering, slow parsing across expiry,
HTML-only manifests, cold file failures and registry outages. Existing daily API
and no-PDF regressions run in the focused SQLite step before the full suite.
