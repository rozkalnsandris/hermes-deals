# Disabled RPi5 origin-monitor installation package

Issue: #170. This package prepares the existing sanitized origin probe and rolling monitor evaluator for later RPi5 activation without enabling or executing monitoring.

## What merging does

Merging only adds repository files. It does not contact the RPi5, install files, reload systemd, enable a timer, start a service, run a probe, deploy Hermes Deals, restart the application, read/write PostgreSQL or change Cloudflare.

## Package components

- `hermes-deals-origin-monitor.service`: hardened one-shot service running as `andris` with a private state directory.
- `hermes-deals-origin-monitor.timer`: five-minute cadence template (`OnUnitActiveSec=5min`), installed disabled.
- `origin-monitor-run.sh`: fixed runtime binding `deals.rozkalns.net` to `http://192.168.0.180:9128`, retaining at most 20 sanitized reports and writing one aggregate summary.
- `bootstrap-origin-monitor-control.sh`: one-time detached exact-SHA registration of the root-owned control dispatcher and immutable package snapshot.
- `origin-monitor-control.sh`: fixed `preflight` or `install-disabled` action used by the self-hosted audit runner.
- manual GitHub Actions workflow: owner identity, merged PR, reachable SHA and current-main blob equality checks.

## Fixed runtime policy

- cadence template: every five minutes;
- report retention: 20;
- monitor window: 5;
- minimum samples: 3;
- alert threshold: 3;
- public URL: `https://deals.rozkalns.net`;
- local origin: `http://192.168.0.180:9128` with host `deals.rozkalns.net`;
- timeout: five seconds.

The runtime keeps sanitized probe reports at `/var/lib/hermes-deals-origin-monitor/reports` and the aggregate summary at `/var/lib/hermes-deals-origin-monitor/latest-summary.json`. State is `0700`; files are `0600`. Raw logs, arbitrary response bodies, credentials, database data and Cloudflare tokens are not collected.

## Registration boundary

The bootstrap is a separate host mutation and is not authorized by merge. When separately approved, it must run as root from a clean detached worktree at the exact merged SHA. The primary `/home/andris/hermes-deals` worktree is refused. It installs only the immutable package snapshot, control dispatcher and narrow sudoers entry. It does not install the monitor runtime or call systemd.

## Workflow modes

### `preflight`

Read-only host verification, apart from writing the sanitized artifact under the runner temporary directory. Authorization must be empty.

### `install-disabled`

Requires the exact phrase:

`INSTALL DISABLED origin-monitor <merge-sha>`

It copies the registered runtime and unit files, compiles/parses them, runs `systemctl daemon-reload`, and verifies service and timer remain disabled and inactive. It refuses to modify an already active or enabled monitor. It never starts or enables either unit and never executes the monitor.

## Activation remains blocked

This package intentionally contains no enable/start workflow mode. Enabling the timer, running the first production probe, retaining live history, exposing alert output or sending notifications requires a separate issue, PR, CI and explicit owner authorization.
