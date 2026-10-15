# ALDI snapshot verification for the Hermes API cutover

Status: **source-only verifier; no production authorization or cutover**.
This is one proof component for [collector issue #992](https://github.com/rozkalnsandris/hermes-deals/issues/992),
not a complete release or state-adoption operation.

The installed ALDI collector service runs from `/home/andris/hermes-deals`
with `docker compose exec -T --user 1000:1000 api` and calls
`app.collector_cli collect --source aldi_nord`. Its normal collection can
write a raw snapshot, a `SourceSnapshot` database row and offer candidates.
These are LIVE data writes and require a separate exact owner authorization.
The service's current source command prints retailer and offer details; a live
operator must capture and sanitize them rather than relay that output.

After an authorized, successful collector run, the API image can run the
read-only `app.aldi_cutover_verify` module with the newly created snapshot UUID
and a UTC timestamp recorded immediately before the collector invocation.
The module is fixed to `aldi_nord` and `/data/raw`. It accepts no caller-selected
source, raw path or API URL. It requires:

- the timestamp to be within the prior 15 minutes and the snapshot to be newer;
- one successful ALDI `SourceSnapshot` row with a valid digest and bounded size;
- a regular, single-link, collector-owned file below `/data/raw/aldi_nord`,
  with no symlink traversal, ACL, world-write, or cross-device path;
- root-owned, collector-group `03775` raw root from the reviewed state adoption;
- file bytes, size and SHA-256 to match the database row without changing it;
- the fixed loopback `GET /api/v1/sources/latest` response to return that same
  latest ALDI snapshot ID, size and digest.

Only fixed `PASS`/`STOP` and no-write markers are printed. Source URL, file path,
hash, content, exception text and API response are kept out of the receipt.
The file read is capped at 32 MiB, the loopback API response at 64 KiB, and
core dumps are disabled. Failure returns nonzero and must stop the cutover.

This verifier does **not** run a collector, deploy an image, inspect Docker's
host bind source, prove that the installed service resolves to the promoted
container, or establish that the direct release path is retired. It proves one
new ALDI snapshot only. The separately authorized host preflight must check
the exact image digest, project/service/container selection and adopted bind,
and the live cutover must prevent concurrent old-path writers before rearming
any timers. The source verifier is not a substitute for schema, backup/restore,
other retailer freshness or household/UI acceptance evidence.

## Host selection proof before any collector write

`tools/verify_aldi_cutover_selection.py` is a source-only, read-only preflight.
Its reviewed inputs are the full API container ID and immutable image SHA-256
from the deployment receipt. Run it on the target host as the collector's
unprivileged `andris` identity, only after a separately authorized API
promotion, with `--expected-container` and `--expected-digest`. Its fixed
working directory and `docker compose ps -q api` selection match the ALDI
unit's `docker compose exec api` context. It requires exactly one Compose API
container, a running healthy API, the reviewed GHCR image ID at that digest,
and the adopted writable raw bind plus read-only config bind. The command
prints only fixed `PASS`/`STOP` and no-write markers; Docker inspection output
and private container configuration are never relayed to the receipt.

Before trusting that proof, separately compare the **installed** ALDI systemd
unit's `WorkingDirectory`, `User`, `HOME`, `ExecStart`, `--user 1000:1000` and
Compose project/service selection with the reviewed source unit. A source unit
alone does not prove what systemd has loaded. Check the installed Netto,
EDEKA collector and EDEKA monitor units and timer state as part of the same
cutover inventory; all three collectors select `api` through the same legacy
checkout, while the monitor reads API/database state. Do not run a collector
merely to test this preflight.

The old direct-main release helper accepts only its managed local
`hermes-deals-api:*` image reference. A promoted GHCR API makes that helper
fail before its build/deploy section, but this source guard does not prove the
installed helper version or prevent a concurrently queued legacy job. The
live packet must verify installed helper identity, quiesce competing release
paths and collector timers, and recheck selection immediately before the
authorized ALDI collector invocation. That invocation writes raw evidence,
`SourceSnapshot` database state and possibly offer candidates. Only afterward
can the read-only snapshot verifier above establish the file/DB/API provenance
link. Neither preflight authorizes those writes or UI activation.
