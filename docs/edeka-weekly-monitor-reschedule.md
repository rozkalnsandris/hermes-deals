# EDEKA weekly monitor schedule migration

This change prepares a bounded migration of the already-registered EDEKA Patzer weekly monitor from:

- `Mon *-*-* 06:15:00 Europe/Berlin`

to:

- `Sun *-*-* 00:10:00 Europe/Berlin`

The EDEKA market/source identity, monitor runtime, service unit, failure unit, retry policy and timeouts do not change.

## Exact registration transition

- monitor source registration commit: `85c3aca4ac62cbffa281365562af52c5e52d8d24`
- old registration fingerprint: `f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb`
- new registration fingerprint: `970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947`
- old timer SHA256: `8f177a8752b9bc9684a87ad3f2f1cd5c367a915591ca6f66d31b0ff8189f34b8`
- new timer SHA256: `6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d`
- service SHA256 remains `d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de`
- failure unit SHA256 remains `c5faf2255c86d8908230449315e5a8b1813b61ae300d4c32899ada9e38c1e9b7`

The new fingerprint is the canonical registration record with only the `OnCalendar` value and the derived timer-unit SHA changed.

## Migration boundary

`tools/runner/reschedule_edeka_weekly_monitor.py` is a root-only, exact-control-SHA migration. It fails closed unless:

- the dedicated EDEKA audit checkout remains clean and pinned to `85c3aca4ac62cbffa281365562af52c5e52d8d24`;
- fetched `origin/main` is the exact authorized control SHA;
- the authorized control SHA descends from both the registered monitor source and the previously registered owner-control commit;
- the running migration bytes and replacement dispatcher are exact Git blobs from that control commit;
- the current registration/control/sudoers/unit bytes still match the old registered state;
- the timer is enabled and active, while the monitor service is inactive and not failed;
- the caller explicitly authorizes the `Persistent=true` catch-up possibility.

A successful migration stops only the timer, atomically replaces the timer unit plus the registration/control trust records and dispatcher/sudoers binding, runs `systemctl daemon-reload`, and starts the timer again. It deliberately does not disable/re-enable the timer, so the existing enablement link is preserved.

If any post-write step fails, the tool attempts to restore the exact old timer, registration, dispatcher, control config and sudoers bytes, reloads systemd and restarts the old timer.

## Authority

Merging this source change does **not** authorize or perform the live migration.

The later live migration requires a separate exact owner authorization covering:

- the merged control SHA;
- old fingerprint `f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb`;
- new fingerprint `970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947`;
- `Sun *-*-* 00:10:00 Europe/Berlin`;
- timer stop/start and `daemon-reload`;
- the possible `Persistent=true` catch-up/source-refetch and the existing bounded retry policy.

The migration contains no production database, Review, publication or deployment write path.
