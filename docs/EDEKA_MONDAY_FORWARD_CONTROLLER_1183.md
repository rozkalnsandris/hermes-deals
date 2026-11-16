# #1183 — EDEKA Monday shadow cutover and verified first scheduled recovery

## Verified LIVE recovery — 2026-11-16 (Europe/Berlin)

The owner-authorized one-shot cutover on Sunday 2026-11-15 completed with
`CUTOVER_SOURCE_AND_TIMER_APPLIED` (exit 0); a separate read-only verification
returned `READONLY_POSTVERIFY_PASS` (exit 0). The dedicated audit checkout was
fast-forwarded to the immutable app source
`684b562084492eebecc76a898b1b5d92e6a8c2e4` and remained clean.
The reviewed controller/source identity is
`4e02d87ea85dd8bd816ea77e558148f13d1ac5d3`. Installed root-owned
service, timer, registration, control JSON, dispatcher and sudoers were verified
against their exact reviewed contents and metadata. No manual or catch-up
monitor run occurred during the cutover.

The **first real scheduled Monday** run on **2026-11-16** started at
**00:10:00 CET**, finished at **00:10:38 CET**, and returned systemd
`Result=success`, `ExecMainStatus=0`. The read-only journal and
`monitor-receipt.json` agree on:

- `result=COMPLETE`, `reason=campaign_current`, `trigger_event=schedule`,
  `exit_code=0`, `stale_days=0`, registered repo SHA
  `684b562084492eebecc76a898b1b5d92e6a8c2e4`.
- EDEKA Patzer campaign valid **2026-11-16 through 2026-11-21** with
  **221 parsed offers**; retained snapshot
  `1cede615-99fd-4062-96c3-69244aea7132` and manifest SHA-256
  `a2847d9c2d5a7aa938dd905e7d328b4099c90160d12d4f6f0be0ddbb0a787a7f`.
- No production database, Review, publication, deployment or scheduler write was
  reported by the scheduled monitor receipt. The affected service journal
  contained no warning-or-higher entries for this run. Notification delivery
  was **not** independently verified; this successful run did not require
  failure notification.
- Timer remained **active/enabled**, `Persistent=true`, next scheduled
  occurrence **2026-11-23 00:10 CET**. Reboot not required.

This confirms recovery **of the isolated EDEKA Monday weekly shadow monitor**
from the Sunday/future-campaign parser mismatch (#1183), **not** the entire
EDEKA production pipeline. Parent [#26](https://github.com/rozkalnsandris/hermes-deals/issues/26)
requires two distinct consecutive weekly campaigns and additional
failure/rollback observations; it stays OPEN. A successful #1183 run does not
prove those remaining acceptance criteria. Evidence and LIVE mutation receipts
are recorded in [#1183](https://github.com/rozkalnsandris/hermes-deals/issues/1183).
Do not manually replay, reset failure states, alter timers, or write production
data without separate scoped owner authority.

## Historical pre-cutover review and one-shot safeguards

The sections below record **dated pre-installation** baselines and the reviewed
one-shot procedure. Their future-tense gates describe what was required **before
the completed 2026-11-15 cutover**; they are not a pending instruction, current
live-state claim, or authority to run the one-shot controller again.

## Fixed, previously reviewed identities

- Installed audit source: `85c3aca4ac62cbffa281365562af52c5e52d8d24`
- Reviewed app source target: `684b562084492eebecc76a898b1b5d92e6a8c2e4`
  (merged #945 parser, #1184 Monday timer and #1189 Python 3.13 runner).
- Existing installed Sunday timer SHA-256:
  `6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d`.
- Reviewed Monday timer SHA-256:
  `214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178`.
- Proposed service SHA-256:
  `d642a9e922a28dfeb982f9930b5091609fd1eebea7e7e27998a8486ab3f77824`.
- Proposed registration fingerprint:
  `19162a6e25844ff21f96f385e11715cecc34d8ede8dad971c03381d911aa0957`.
- Proposed canonical registration-file SHA-256:
  `6fa3268c6add7e0356654a231b7d1f9dee87d06d76d6949a861cd6278cc95d7e`.

Read-only RPi5 source-of-truth baseline and old host metadata:
[`EDEKA_MONDAY_FORWARD_PREFLIGHT_1183.md`](EDEKA_MONDAY_FORWARD_PREFLIGHT_1183.md).
The entries in this historical proposal are **pre-cutover expected values**. The verified 2026-11-16 runtime outcome is recorded above; do not interpret this old proposal as today's host state.

## Historical Python 3.13 source rebind and provisioning gate (2026-11-15)

The obsolete Monday controller target `afe83b066ab97a41b269433e288401b1f0465eac` retained a
Python 3.11 shadow runner while the active lock manifest required Python 3.13.
Its old service hash `412d04a122d895e75df9d99749a888f4c77767f8d52438d5f89193103e0dc9f5` and registration fingerprint
`0bcc33eda2d25ec556e8e7d7176984b16b23a1845e464e428176375661761c61` are **superseded and must not be installed**.

PR #1189 merged to immutable app source `684b562084492eebecc76a898b1b5d92e6a8c2e4`, with Python 3.13
shadow runner, active `runtime-py313.txt` manifest entry and wheel-locked
dependency verification. The forward controller, root dispatcher, GitHub
owner-control exact pair and read-only helper are rebound to that immutable
source and the candidate hashes above. The controller verifies the reviewed
Git source runtime contract and additionally requires CPython 3.13 and
`ensurepip` to be executable by `andris` on the ARM64 host **before any
cutover mutation**.

**Pre-provisioning observation (2026-11-15, since superseded):** the host had
`/usr/bin/python3 = 3.11.2` and lacked `python3.13`. A separate owner-authorized
LIVE operation subsequently installed isolated Python 3.13.18 without replacing
system Python. Immutable Git object/controller staging and the one-shot cutover
were separately authorized and completed. **Do not repeat `--phase=apply`:** its
one-time authorization was consumed.

## Source boundaries

1. `tools/runner/edeka_monday_forward_cutover.py` is a one-shot
   **owner-gated** root controller. In `--phase=preflight`, it only reads
   already staged, immutable Git objects, exact old root file bytes/metadata,
   the timer state and source checkout. It produces sanitized candidate hashes
   with no host changes. **Do not stage it onto RPi5 as part of this source PR.**
2. New `tools/runner/edeka_weekly_monitor_control_monday.py` retains the
   existing root dispatcher contract with exactly five binding substitutions
   and a fail-closed activation-error change. The new dispatcher must be
   installed under the **existing exact** root-controlled destination;
   the old one must not be left active against a new registration.
3. The existing GitHub owner authorizer uses a **two-pair exact allowlist**:
   old source SHA + old fingerprint, and reviewed Monday source SHA + new
   fingerprint. Cross-pairs are rejected. This permits already authorized
   old-host control to remain functional until owner-approved cutover; it does
   not authorize either operation or accept another source/store.
   For new bindings the GitHub authorizer additionally requires the new
   dispatcher and forward-controller files at the reviewed control commit.
4. `--phase=apply` is **not** current authorization. Future explicit owner
   LIVE consent must bind host `rpi5`, exact old baseline digests, the app
   source target above, a **new exact immutable Git control SHA** (resolved
   after this source PR is merged), the once-only approved mutation set and
   `EXACT-ONE-SHOT-MONDAY-NO-CATCHUP`. A GitHub MERGE is never LIVE consent.

## Required preconditions for future owner-gated LIVE session

- GitHub `main` and exact reviewed controller SHA freshly resolved; current
  required checks/reviews clean. The controller SHA must descend from the
  pinned app SHA. The new source tree and staged script must be exact
  Git objects (the controller checks its own Git blob and the new dispatcher).
- Before any cutover write, the necessary exact Git objects and root-owned
  controller source must already have been staged under **separately explicit
  LIVE scope**. Git fetching, downloading, copying, permissions, or changing
  an audit checkout are mutations, not harmless preflight steps. If staging
  fails, STOP — no retry or cleanup.
- Real installed RPi5 baseline must still match all pinned hashes, modes,
  ownership, registration/control config, clean old audit checkout, original
  repository URL, `systemd` service `failed/exit30`, and
  timer `active/enabled` with the latest trigger on **the same Sunday
  00:10**. The existing RPi5 maintenance/shared application locks must be
  checked. No unrelated maintenance may overlap.
- Apply allowed only on **Sunday 02:00–23:29 Europe/Berlin**, after the
  existing Sunday invocation and before the next Monday 00:10 trigger.
  The timer retains `Persistent=true`; this gate forbids accidentally
  replaying an already-missed Monday run. If the window is missed, STOP,
  obtain a new policy/owner decision rather than forcing a catch-up.
- No manual monitor run, production source collection, DB/Review/publication
  write, storage cleanup, Docker change, global alert scanner or reboot is
  included.

## Planned strictly ordered effects after separate LIVE approval

The controller acquires an exclusive one-shot advisory lock and **rechecks
all old state under the lock**. It then stops only the existing EDEKA timer,
fast-forwards only the dedicated clean EDEKA audit checkout to the exact
reviewed app SHA (no fetch, no reset), atomically replaces the exact EDEKA
service/timer, root registration, reviewed dispatcher, control JSON and
sudoers; executes one `systemctl daemon-reload` and starts the existing
enabled timer only if the Sunday no-catch-up gate still holds.
The EDEKA failure alert unit is not changed.

Every mutation must be in the approved exact order; there are **no retries,
fallbacks or automatic rollback**. After an error or drift, capture minimum
read-only evidence and STOP. Incomplete state is possible and requires
fresh authorization for any recovery action. Existing service failure evidence
is preserved; the controller does not `reset-failed` or manually run the
monitor.

A successful file/timer change is **not** EDEKA recovery. Verify actual
Monday scheduled source/campaign evidence, exact-market parser output and
app-owned failure notifications separately. Keep #1183/#26 open until that
evidence is confirmed.

## Deployment preparation still requires operator-specific review

The source PR intentionally contains **no** GitHub Actions LIVE workflow
trigger, credentials, new sudoers grants or automatic deploy. The control SHA
must be available in the audit checkout's Git object database *before*
executing the root controller; new Git objects cannot be fetched implicitly.
Future staging, any required explicit host locks and first-run LIVE authorization
must be prepared against fresh host evidence and the approved control source
commit. Do not treat this runbook as a paste-and-run deployment command.
