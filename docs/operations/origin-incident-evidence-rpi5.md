# Hermes Deals origin incident evidence audit

This audit is the service/resource evidence companion to the public-versus-local origin probe. It is intended for a known incident timestamp, such as the Cloudflare 502 observed on 2026-08-04 at 23:11 UTC.

Merging the implementation **does not install** the collector or dispatcher and **does not execute** the workflow. Installation and every workflow run require separate explicit owner authorization.

## Evidence boundary

The collector records only deterministic structured data:

- canonical UTC incident timestamp and the selected ±5, ±15, ±30 or ±60 minute window;
- current host uptime, load averages, memory totals/availability, swap totals/free space and root filesystem capacity;
- whether TCP port `9128` is currently listening;
- kernel OOM signature count inside the requested journal window;
- fixed Docker state fields for the Hermes Deals `api`, `web` and `db` services;
- fixed Docker state fields for one detected Cloudflare Tunnel container;
- restart count, OOM flag, exit code and health status;
- allowlisted integer counters for gateway 502, upstream, timeout, reset, database, exception, OOM and reconnect signatures;
- collector completeness/partial status and allowlisted partial-reason codes.

No raw journal or container log lines are included. The artifact also excludes container names, IDs, images, commands, environment variables, labels, mounts, Docker health-check output, request bodies, URLs, tokens, credentials and arbitrary command errors.

The collector uses a 12-second command timeout and a 2 MiB input cap for every Docker or journal command. A capped, timed-out or unavailable source is marked partial instead of expanding the artifact.

## What this audit does not do

- It does not restart, stop, recreate or signal a service or container.
- It does not change Cloudflare Tunnel, nginx, Docker, systemd or firewall configuration.
- It does not read or write PostgreSQL and does not run application queries.
- It does not deploy an image, run Alembic or publish Review items.
- It does not expose the Cloudflare Tunnel command, token, environment or credential files.
- It does not verify the remotely managed Cloudflare ingress mapping.
- It does not claim a root cause; it produces evidence for issue #44 analysis.
- It does not touch B15M2 V08.

## One-time installation after merge

Use a clean detached worktree at the exact squash-merge SHA. The primary production worktree `/home/andris/hermes-deals` is forbidden as the installer source.

```bash
sudo tools/runner/install-origin-incident-evidence.sh \
  /home/andris/hermes-deals-worktrees/release-control \
  <exact-squash-merge-sha>
```

The installer:

1. verifies the detached clean SHA is reachable from `origin/main`;
2. compiles the Python collector and parses the dispatcher with `bash -n`;
3. installs root-owned immutable copies;
4. records SHA256 identities in `/etc/hermes-deals-audits.d/origin-incident-evidence.conf`;
5. grants `github-runner` sudo access only to the fixed dispatcher command;
6. prints `WORKFLOW_EXECUTED=false` and performs no audit.

Installation requires separate explicit owner authorization.

## Manual workflow execution

Run **Hermes Deals origin incident evidence RPi5 audit** with:

- `pr_number`: the merged PR that registered the exact installed files;
- `incident_at`: canonical UTC timestamp, for example `2026-08-04T23:11:00Z`;
- `window_minutes`: one of `5`, `15`, `30`, `60`.

The GitHub-hosted authorization job verifies the exact owner login and numeric ID, merged PR, reachable merge SHA, canonical timestamp, bounded window and required tree paths. The self-hosted job performs no repository checkout.

Workflow execution requires separate explicit owner authorization.

## Artifact

The uploaded artifact contains only:

- `incident-evidence.json` when collector output passes the independent dispatcher schema validation;
- `dispatcher-manifest.json`;
- `audit-exit-code.txt`.

`collector_exit_code=0` means all required sources were collected. `collector_exit_code=2` means a valid sanitized partial report was produced. Any other non-zero code is a collector or dispatcher failure and must not be interpreted as evidence of an origin root cause.

## Interpreting evidence

Useful combinations include:

- healthy local listener and services plus Cloudflare reconnect/gateway counters: investigate the public edge/tunnel path;
- web upstream counters with a running API: investigate nginx-to-API connectivity and timing;
- API exception/database counters with DB health degradation: investigate API-to-PostgreSQL behavior;
- restart count, OOM flag or kernel OOM signatures: investigate host/container resource pressure;
- complete zero counters: the retained logs may not cover the historical incident; do not infer that no incident occurred;
- partial report: resolve the missing collector source before drawing a conclusion.

Exact Cloudflare ingress target verification and any production reliability change remain separate issue #44 work with separate authorization.

## Removal

```bash
sudo tools/runner/install-origin-incident-evidence.sh --remove
```

Removal deletes only the installed collector, dispatcher, registration and dedicated sudoers entry. It does not restart services or alter production data.
