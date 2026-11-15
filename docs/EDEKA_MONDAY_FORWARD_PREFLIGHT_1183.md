# EDEKA #1183 — Monday forward cutover: verified baseline and next gate

This is a **non-activating** continuity artifact following merged PR #1184.
It does **not** authorize or perform any LIVE/RPi5 mutation.

## Dated source and installed baseline

GitHub `hermes-deals/main` observed at
`afe83b066ab97a41b269433e288401b1f0465eac`, which includes the
market-bound weekly header parser (#945) and the reviewed Monday timer (#1184).
The intended **source-registration target** for this cutover proposal is that
exact immutable commit, even if a later documentation/preflight PR advances main.
Every actual future LIVE preflight must still verify fresh GitHub/main and the
reviewed target's ancestry and source blob identities.

Read-only RPi5 evidence observed 2026-11-15 11:57 CET:

| Installed resource | Exact current identity |
| --- | --- |
| Dedicated EDEKA audit checkout | `main@85c3aca4ac62cbffa281365562af52c5e52d8d24`; clean |
| `hermes-edeka-weekly-monitor.service` | root:root 0644, SHA-256 `d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de` |
| `hermes-edeka-weekly-monitor.timer` | root:root 0644, SHA-256 `6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d` |
| `hermes-edeka-weekly-monitor-failure@.service` | root:root 0644, SHA-256 `c5faf2255c86d8908230449315e5a8b1813b61ae300d4c32899ada9e38c1e9b7` |
| Unit registration JSON | root:root 0600, SHA-256 `30a1b547d75b3d30783207cfa5d2a8fc55570288b4b30280fbd576ba4684b20c`, registration fingerprint `970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947` |
| Control JSON | root:root 0600, SHA-256 `e5db173460f56f19d5fb38400864d553c2dd53262e96eaa30bab766d6e2e9789`, control SHA `19edda8c1312ea6362331bdceabe14efd11beacd` |
| Installed control dispatcher | root:root 0755, SHA-256 `c414dfc2b0fd5eaafde148e79b2585c82233fd2fed3baf6b1296fffcf9ba2b38` |
| Installed sudoers scope | root:root 0440, SHA-256 `3bb947a9417edf811e3d5b6a216bd3509da3d92e2fadfca179de74550874c593` |

Timer is `enabled/active` at `Sun *-*-* 00:10:00 Europe/Berlin`;
next scheduled occurrence was 2026-11-22 00:10 CET. Service remains
`failed`, `ExecMainStatus=30`, `NRestarts=3`. The RPi5 maintenance
exclusive lock was unheld; `/run/reboot-required` absent. These are **dated
observations** and do not authorize a later mutation.

## Current non-mutating verification tool

`tools/edeka_monday_cutover_readonly_preflight.py` runs a read-only,
root-owned-files and Git inspection against that exact baseline. It rejects
unknown bytes, metadata, source checkout SHA/branch/dirty state, origin, schema,
registration/control hashes, or an unsafe flag. It reads only and prints
sanitized identifiers; no target config contents or credentials are reported.

The pure `build_readonly_proposal` function computes the deterministic
one-line timer change and the proposed source-pin-only service change, their
SHA-256 hashes, and a **candidate** registration fingerprint derived from
the exact old configuration with only those reviewed fields changed.
It does **not** generate or install a new root controller/dispatcher/sudoers,
does not fetch or reset source, and deliberately returns
`live_mutation_ready=false`. The tool itself must be run only from a verified
reviewed source identity; installing/staging it on RPi5 is itself a separate
LIVE action if it writes a file there.

This is intentionally **not** a command to install the Monday timer.
The historical `tools/runner/reschedule_edeka_weekly_monitor.py` only
migrates the older Monday schedule **to Sunday** and contains obsolete pins;
never reuse it for this forward migration.

## Separate forward-migration source gate

Before requesting LIVE authority, independently review an exact,
**forward-only** controller (new source task/PR) that binds:

1. GitHub reviewed EDEKA app source `afe83b066ab97a41b269433e288401b1f0465eac`;
   source checkout origin, clean baseline and target ancestry; **no
   unpinned** `origin/main` fetch/checkout operation.
2. New registration fingerprint, service and timer bytes, new canonical
   control dispatcher source and its Git blob/hash, control metadata and
   corresponding sudoers policy. The old root controller is hard-pinned to
   the old registration SHA, timer hash and fingerprint; replacing only
   `OnCalendar` or only the checkout would break the trust contract.
3. An explicit no-auto-catch-up strategy for `Persistent=true`, with
   an owner review of whether to retain it, when and how the timer is
   reactivated, and what scheduled execution (retained evidence writes)
   is authorized. A manager reload/timer start can execute work even
   without a manual service start.
4. Exact one-shot fail-closed semantics: recheck all expected installed
   bytes/metadata and service/timer state, hold the required exclusive lock,
   perform only the owner-approved mutations, then read-only verify.
   After the first mutation, unexpected drift/error/timeout means evidence
   and **STOP**, never automatic rollback, retries, prune or restart.
5. Continued isolation: no production DB, Review/publication, broad
   collector, source mapping, credentials, Lidl timer, or reboot changes.

A separate **owner MERGE** decision is needed for this source-only preflight
PR. After the executable forward-migration controller is itself merged and
reviewed with exact identities, a separate **owner LIVE** authorization is
required. Neither source PR merge nor a dry-run plan is a successful RPi5
cutover. Real resolution of #26/#1183 needs a genuine Monday scheduled
cycle, retained source/campaign evidence and current timer/alert verification.
