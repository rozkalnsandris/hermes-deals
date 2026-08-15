# EDEKA weekly monitor owner-control boundary

This boundary follows merged PR #672 and adds the source-only control path for later owner-authorized EDEKA weekly-monitor activation, disable and rollback.

## Trust chain

The GitHub bridge accepts commands only from repository owner `rozkalnsandris` / sender id `277435981` on issue #26. It verifies that PR #673 is merged into `main` and remains reachable from current `main` before any self-hosted work.

The self-hosted job may invoke only the fixed root-owned dispatcher `/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control`. A separate root-registration helper installs that dispatcher and a regex-bounded sudoers rule only after the PR is merged and after the non-activating unit registration from PR #672 already exists for the same exact current-main SHA.

The root dispatcher reloads and validates the root-owned PR #672 registration record, recomputes its fingerprint, verifies the exact planner/runtime/unit-registration blobs, verifies every installed unit SHA-256 and runs `systemd-analyze calendar` plus `systemd-analyze verify` before any systemd mutation.

## Owner command matrix

Activation is deliberately stricter than shutdown paths because the timer uses `Persistent=true`: starting it can immediately catch up a missed schedule and therefore may immediately run the EDEKA shadow source refetch. Activation also enables the bounded retry policy already encoded in the registered service unit.

Exact activation command after all registration gates pass:

`/hermes-edeka monitor activate pr=673 sha=<REGISTERED_SHA> registration=<REGISTRATION_FINGERPRINT> refetch=authorized retries=authorized`

For `activate`, `<REGISTERED_SHA>` must equal GitHub current `main` at authorization time and the dedicated EDEKA audit checkout must still be clean `main` with exact `HEAD == origin/main == <REGISTERED_SHA>` on the RPi5. Missing either explicit authority token fails closed.

Exact safety commands:

`/hermes-edeka monitor disable pr=673 sha=<REGISTERED_SHA> registration=<REGISTRATION_FINGERPRINT>`

`/hermes-edeka monitor rollback pr=673 sha=<REGISTERED_SHA> registration=<REGISTRATION_FINGERPRINT>`

`disable` and `rollback` intentionally do not require the historical registration SHA to remain equal to current GitHub `main`. That keeps the emergency stop/rollback path usable even if the repository advances after activation. The root dispatcher still requires the exact root-owned registration SHA/fingerprint and exact installed unit bytes.

## Operation semantics

`activate` performs an explicit `daemon-reload`, then `enable --no-reload` and `start` for only `hermes-edeka-weekly-monitor.timer`. It never directly invokes the EDEKA collector; however a `Persistent=true` timer may start the registered service immediately, so source refetch and bounded retries are explicitly authorized by the owner command.

`disable` stops the timer and service, disables the timer with `--no-reload`, reloads the manager, resets failed state and verifies the timer/service are inactive and the timer is not enabled. It does not remove unit files or evidence.

`rollback` first performs the disable path, then removes only the three exact checksum-verified EDEKA monitor unit files and the exact root-owned PR #672 registration record, reloads systemd and verifies the monitor is absent/inactive. The shadow evidence root, monitor evidence root and cache root are preserved. The separately registered control dispatcher/sudoers trust root is intentionally preserved so rollback evidence can be returned and a later exact registration can be controlled again.

## Registration-only boundary

After PR #673 is merged, live preparation remains two separate root/host actions:

1. register the PR #672 unit files and schedule against the then-current exact `main` SHA;
2. register the PR #673 control dispatcher/sudoers trust root against that same exact SHA.

Neither registration step enables, starts or reloads the timer. Each requires its own explicit owner authorization.

## Production authority

The monitor runtime remains shadow/read-only with respect to production DB, Review and publication state. The control path never authorizes production DB write, Review write, publication write or production deploy.

Merging this PR alone performs none of the following: root/host mutation, unit/control registration, systemd reload, timer activation, source refetch, bounded retries, production write or deploy.
