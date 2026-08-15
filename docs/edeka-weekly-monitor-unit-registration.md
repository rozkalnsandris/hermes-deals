# EDEKA weekly monitor unit registration boundary

This boundary follows merged PR #671 and prepares a later owner-authorized host registration without activating the weekly timer.

## What the installer may do after separate owner authorization

`tools/runner/install_edeka_weekly_monitor_units_nonactivating.py` is checksum-bound to an exact merged `main` commit and to the reviewed #671 planner/runtime blobs. It accepts explicit operator inputs for `OnCalendar`, retry delay/window, max attempts, service timeout and runner timeout.

Before writing unit files it regenerates the #671 activation plan, verifies the exact schedule and all safety flags, verifies every generated unit digest, then runs `systemd-analyze calendar` and `systemd-analyze verify` against the generated files.

A successful registration may create the three fixed 0700 `andris` data roots when absent, install the three fixed unit files as root:root 0644 under `/etc/systemd/system`, and create one root:root 0600 registration record containing the exact source blobs, schedule, unit hashes and a deterministic registration fingerprint.

Existing unit/config paths are create-once-or-identical. Unknown bytes, symlinks or metadata drift fail closed.

## What registration explicitly does not do

Registration does not run the EDEKA monitor, refetch EDEKA, reload the systemd manager, enable or start the timer, activate retries, write production DB/Review/publication state, or deploy production.

The installer only uses `systemctl is-active` and `systemctl is-enabled` as read-only guards before and after filesystem registration. If a monitored unit is already active or the timer is already enabled, registration fails closed.

There is deliberately no `daemon-reload`, `enable`, `start`, `restart` or `--now` path in this installer. A later activation control boundary must verify the registered fingerprint and unit bytes and requires its own explicit owner authorization.

## Operator boundary after merge

Merge alone does not authorize host/root work. Before registration, choose the schedule/retry values explicitly and bind the authorization to the then-current exact `main` SHA. The later root command must use only those reviewed values and the exact merged SHA.

After registration, keep the timer unloaded/disabled/inactive until a separate activation authorization and control path are reviewed.
