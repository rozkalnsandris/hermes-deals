# EDEKA weekly monitor activation control boundary

This source boundary starts only after the #672 non-activating unit registration has succeeded on RPi5.

Authoritative registered monitor identity:

- monitor source commit: `85c3aca4ac62cbffa281365562af52c5e52d8d24`
- registration fingerprint SHA256: `f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb`
- service unit SHA256: `d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de`
- timer unit SHA256: `8f177a8752b9bc9684a87ad3f2f1cd5c367a915591ca6f66d31b0ff8189f34b8`
- failure-alert unit SHA256: `c5faf2255c86d8908230449315e5a8b1813b61ae300d4c32899ada9e38c1e9b7`

The registered service remains pinned to that exact monitor source commit. Merging this control source therefore must **not** advance the dedicated `/home/andris/hermes-deals-audit-source-edeka` working tree. The later control-registration operator step fetches `origin/main` but leaves local `HEAD` pinned to the monitor registration commit.

## Owner commands

After this control PR is merged and its root dispatcher is separately registered, commands are accepted only from the repository owner on issue #26:

```text
/hermes-edeka monitor activate control=<CONTROL_SHA> registration=85c3aca4ac62cbffa281365562af52c5e52d8d24 fingerprint=f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb refetch=authorized retries=authorized
/hermes-edeka monitor disable control=<CONTROL_SHA> registration=85c3aca4ac62cbffa281365562af52c5e52d8d24 fingerprint=f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb refetch=forbidden retries=forbidden
/hermes-edeka monitor rollback control=<CONTROL_SHA> registration=85c3aca4ac62cbffa281365562af52c5e52d8d24 fingerprint=f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb refetch=forbidden retries=forbidden
```

`CONTROL_SHA` is the exact commit used for the separately owner-authorized root control registration and must remain reachable from current `main`.

`activate` additionally requires a completed/success Hermes Deals push CI for current `main`. `disable` and `rollback` deliberately do not depend on current-main CI so the safety shutoff path remains available after unrelated source movement.

## Activation semantics

The root dispatcher revalidates the root-owned #672 registration record, recomputes its deterministic fingerprint, checks every installed unit byte and mode, and requires the dedicated EDEKA checkout to remain clean at the registered monitor SHA.

Activation then:

1. runs `systemd-analyze calendar` and `systemd-analyze verify`;
2. requires the timer disabled/inactive and the monitor service not active;
3. performs `systemctl daemon-reload`;
4. enables the timer without an extra implicit reload;
5. starts the timer separately;
6. verifies timer enabled and active.

The timer uses `Persistent=true`. Starting it may therefore immediately catch up a missed activation. The owner command must explicitly authorize both source refetch and the already reviewed bounded-retry behavior. The receipt says that refetch **may have been triggered** rather than claiming a network action was definitely observed.

If activation fails after manager mutation starts, the dispatcher attempts a fail-safe cleanup and does not return PASS unless the timer is disabled/inactive and the monitor service is not active.

## Disable and rollback

`disable` stops the timer/service, disables the timer, reloads manager state, verifies a safe inactive result, and preserves:

- all three registered unit files;
- the #672 registration record;
- shadow evidence;
- monitor evidence;
- hash-locked runtime cache.

`rollback` first performs the same safe disable. Immediately before deletion it re-reads and revalidates the root-owned registration/control identity and all exact unit bytes, then removes only the three registered EDEKA monitor unit files and reloads systemd. Registration/control records and all evidence/cache roots remain retained as audit evidence.

Neither operation authorizes source refetch, bounded retries, production DB/Review/publication writes, or production deploy.

## Root control registration

Merge does not install this control bridge. A later, separately owner-authorized operator step must:

- fetch the merged control commit into the dedicated EDEKA repository without advancing its pinned local HEAD;
- extract the checksum-verified control installer from the Git object database;
- run it as root with the exact control SHA and registration fingerprint.

The installer validates the existing #672 registration fingerprint, exact Git ancestry and source blobs, validates a fixed sudo policy with `visudo`, and installs only:

- `/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control`
- `/etc/hermes-deals-audits.d/edeka-weekly-monitor-control.json`
- `/etc/sudoers.d/hermes-deals-edeka-weekly-monitor-control`

It does not call `systemctl`, reload systemd, enable/start the timer, refetch EDEKA, or write production application state.
