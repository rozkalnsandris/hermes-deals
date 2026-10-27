# PDF retention inventory

Tracking: [#1069](https://github.com/rozkalnsandris/hermes-deals/issues/1069).
The source audit is pinned to `522061bad52111db0fbbadb11cc012bbc811badb`.
This first tool inventories explicitly selected local directories. It does not
implement the 30-day lifecycle or prove that deployed storage complies.

## Run the read-only inventory

```sh
python tools/pdf_retention_inventory.py /absolute/path/to/raw /absolute/path/to/corpus
```

The command writes JSON to stdout. Its default mode uses only Python's standard library on Linux.
By default it does not connect to a retailer or database, extract archives, render documents,
modify source files, delete files, or install a scheduler. No default directory is
scanned. Only supply exact storage roots covered by the current task's read scope;
do not use a home directory as a substitute for a storage inventory.

Results group identical bytes by SHA256 and kind, with every observed location.
Root indexes refer to the sorted `roots` list. PDF detection examines the first
1024 bytes, including files called `source.bin`; this detects candidates rather
than validating the PDF document structure. Misnamed `.pdf` files are reported.
PNG/JPEG/GIF/WebP/TIFF files are image candidates, not proven booklet derivatives.
ZIP/tar/compressed files are reported as uninspected archives; their members are
not counted. Encrypted, embedded/base64 and other unrecognized formats require
separate inventory. Hard links are reported as separate locations.

Exit code 0 means traversal of the selected roots completed; it **does not** mean
all copies were found or their retention is compliant. Exit code 2 means an input
error or partial inventory. Skipped symlinks, special files, read failures,
changed files and exceeded limits are explicit findings. Child files are opened
relative to directory descriptors without following symlinks. This is a bounded
observation of mutable storage, not an atomic filesystem snapshot.

Default limits: 16 roots, 10,000 directory entries, 256 MiB per file, 4 GiB of
content read. Override with `--max-files`, `--max-file-bytes` and
`--max-total-bytes`. Roots must be absolute, non-overlapping directories without
symlink components. Images may be unrelated product/UI assets: never delete them
solely because they appear here. Output contains local paths; review it before
publishing a public receipt.

## No invented retention dates

Without `--with-registry`, `first_acquired_at` and `expires_at` are null. Filesystem mtime/ctime, archive
upload time, retailer publication time and source.json dateTime are not accepted
as proof of the first acquisition. A copied/redownloaded PDF can have a recent
mtime while already being older than 30 days.

The [acquisition registry](pdf-acquisition-registry.md) binds evidence of first
acquisition to content SHA256. The optional report below applies its existing
calculation to observed PDF copies. Preview parent binding remains unimplemented.
This tool does not consume a guessed timestamp or produce an executable deletion
plan. Its output is inventory input, not a deletion authorization.

## Compare observed PDFs with the registry

Using the backend's installed dependencies and an explicitly configured
`DATABASE_URL` environment variable:

```sh
python tools/pdf_retention_inventory.py /absolute/path/to/raw --with-registry
```

This is the same command and traversal. Registry mode requires
`postgresql+psycopg`, the existing migrated acquisition table and read access.
It does not read a default database URL or load app startup/configuration. Keep
credentials in the execution environment, not in arguments or published output.
No database schema, acquisition rows, source snapshots or prices are written.
A connection/driver/schema/query error exits 2 with a generic diagnostic and no
JSON; it never silently falls back to an unannotated or partly annotated result.

The connection owns one PostgreSQL REPEATABLE READ, READ ONLY transaction and
verifies the server's read-only setting. Connection and individual statement
timeouts are 10 seconds. The existing inventory limits also bound the number of
PDF groups queried. One UTC wall-clock timestamp, captured after file traversal,
is used for all evaluations; no CLI option can reset acquisition dates. The
report is an observation, not a filesystem lock or a current deletion plan.

Enriched JSON uses `schema_version: 2` and adds `registry_checked_at`. Each
`kind: pdf` group keeps its observed copies and receives `acquisition_status`,
`first_acquired_at` and `expires_at` from the existing `pdf_retention` function.
States include `within_retention`, `raw_expired`, `acquisition_unknown`,
`unregistered` and `not_yet_acquired`. Unknown evidence stays unknown even if a
newer download exists; a known expired upper bound can still prove expiry.
Every duplicate location in one group shares the same content deadline.

Archives, images and invalid PDF headers keep unknown dates; they are not
promoted to verified PDF copies by a registry match. Partial findings and all
coverage flags are preserved. Even an all-green selection keeps
`retention_compliance: unknown` and `deletion_authorized: false`: backup/archive
coverage, preview bindings and physical cleanup are not proven by this report.
Exit 0 still means traversal/report completion, including when expired PDFs were
observed; it is not a compliance verdict. Default output remains schema version
1 with no database dependency. No scheduled job or production invocation is
activated by adding this mode.

## Audited storage and reader boundaries

| Boundary | Current owner | Consequence |
| --- | --- | --- |
| Runtime raw mount | `docker-compose.yml`: ./data/raw → /data/raw | Do not delete the whole raw directory. |
| ALDI/EDEKA | `probe.py`, `edeka_store_offers.py`: HTML/JSON + manifests | Keep non-PDF source and price records. |
| Netto PDFs | `netto_store_prospect._write_bundle`; weekly/held-out callers select separate raw roots | Same SHA may have multiple locations/observations. V3 replay requires PDF bytes even when dates came from HTML. |
| Netto primary reads | `netto_html_read.verified_html_rows` → HTML replay | HTML remains necessary independently of PDF expiry. |
| Kaufland | `kaufland_evidence_freeze.py`: source.bin with MIME/SHA metadata | Extension alone cannot classify the retained content. |
| Lidl | discovery family-*/source.pdf → staging flyers/*/source.pdf → frozen corpus | All materialized copies share the original deadline. |
| Lidl readers | `lidl_corpus_import.load_context`, staging reference and corpus promotion | Missing PDF currently fails; planned expiry needs an explicit state. |
| Lidl previews | `render-lidl-review-previews.py`, `lidl_review_preview.py` | PNG availability must inherit expiry; current reader checks format/path, not age. |
| CI/archive | Netto held-out uploads full source root for 14 days | Upload TTL alone does not enforce 30 days from first acquisition. |
| Historical independent copy | `audit/netto/hz37/independent-retention-receipt.json` | Receipt declares retention through 2026-12-31; reconcile with the new policy through a new event, not by rewriting old evidence. |

Netto scheduled transition/shadow artifacts have 35-day retention but explicitly
upload JSON/checksum metadata only. That is not proof of an over-retained PDF.
The Lidl R2 scan uses a temporary source PDF and checks that raw source files did
not enter its retained result. Release images copy app/alembic; raw is a separate
mount. None of those observations confirms the current RPi disk or backup state.

## Remaining implementation

- [ ] Inventory deployed raw, discovery, staging, corpus, request/work directories,
  previews, archive members, Actions copies, downloads and backups.
- [ ] Persist first acquisition evidence once per content SHA; copying or
  redownloading never resets the deadline. Unknown age remains unresolved.
- [ ] Keep immutable source observations and structured price/product/offer links;
  represent lifecycle events separately.
- [ ] Make readers distinguish `raw_expired` from missing/corrupt/never-acquired.
  Never report full replay without bytes or call expiry `verified_no_pdf`.
- [ ] Expire PNG/crop derivatives and reject re-materialization after the deadline.
- [ ] Add one dry-run/apply cleanup entrypoint with exact paths, SHA checks and
  per-copy results; do not mutate price/history tables.
- [ ] Enforce physical expiry no later than first acquisition + 30×24h.
  Daily cleanup after day 30 can retain files for nearly 31 days; schedule early
  enough, bound retries and surface missed deadlines. Reader denial is necessary
  but is not a substitute for deleting retained copies.
- [ ] Cover 29/30/31-day boundaries, timezone, duplicate acquisition, archive
  restore, unknown ages, path races, partial deletion and surviving price history.
- [ ] Reconcile historical archive/backup contracts before lifecycle activation.

This source change neither activates cleanup nor alters the Offers UI.
