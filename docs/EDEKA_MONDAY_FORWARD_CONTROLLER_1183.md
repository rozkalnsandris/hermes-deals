# #1183 — EDEKA Monday shadow cutover controller (source-only review)

## Fixed, previously reviewed identities

- Installed audit source: `85c3aca4ac62cbffa281365562af52c5e52d8d24`
- Reviewed app source target: `afe83b066ab97a41b269433e288401b1f0465eac`
  (merged #945 parser and #1184 Monday timer).
- Existing installed Sunday timer SHA-256:
  `6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d`.
- Reviewed Monday timer SHA-256:
  `214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178`.
- Proposed service SHA-256:
  `412d04a122d895e75df9d99749a888f4c77767f8d52438d5f89193103e0dc9f5`.
- Proposed registration fingerprint:
  `0bcc33eda2d25ec556e8e7d7176984b16b23a1845e464e428176375661761c61`.
- Proposed canonical registration-file SHA-256:
  `9ca5e1892ff48c86dad6e1217ea159e2776e1b8f76ae42d7d7587ae816ec419b`.

Read-only RPi5 source-of-truth baseline and old host metadata:
[`EDEKA_MONDAY_FORWARD_PREFLIGHT_1183.md`](EDEKA_MONDAY_FORWARD_PREFLIGHT_1183.md).
All hashes are **expected values**, not evidence that LIVE has been updated.

## Python 3.13 prerequisite — HOLD (2026-11-15)

The original Monday forward controller was reviewed against application source
`afe83b066ab97a41b269433e288401b1f0465eac`. That commit has the
market-bound EDEKA parser fix but retains the 3.11 shadow runner while its
active `backend/locks/manifest.json` has *only* `runtime-py313.txt`.
Consequently that original application SHA is **not executable** for a
successful EDEKA Monday shadow cycle. Its cutover MUST NOT be authorized
or run; source SHA/fingerprint hashes below are historical proposal
identities, not approval to use them.

The source-only Python 3.13 change introduces a strict source-level
`validate_exact_python313_source` gate in the forward controller, checking
the pinned application Git blob, exact active manifest and runtime lock
*before* any cutover mutation. The old pinned SHA fails this guard.

After a reviewed **new application source commit is merged**, a further
GitHub source-only PR must explicitly rebind the forward controller's
`APP_SOURCE`, service SHA-256, registration JSON/fingerprint, dispatcher,
GitHub owner-control allowlist and tests to that **new exact immutable SHA**.
Do not reuse the old `afe83...` application pin or its calculated
registration fingerprint. The new RPi5 runtime also needs a real verified
CPython 3.13 interpreter, not currently provided on the host. Interpreter
provisioning, storage/cache changes, source staging, root controller
installation, Git object fetch and any systemd mutation are all **separate
explicit LIVE owner gates**, not part of a source merge.

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
