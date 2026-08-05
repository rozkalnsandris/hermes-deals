# Owner-authorized RPi5 public-origin audit

This audit compares the public Cloudflare path with the local Hermes Deals nginx
origin by running the sanitized probe added in issue #86.

It is a diagnostic path only. Installing or running it does not authorize a
restart, deployment, configuration change, database write, Review action or
B15M2 V08 execution.

## Repository components

- `.github/workflows/origin-path-rpi5-audit.yml`
- `tools/runner/install-origin-path-rpi5-audit.sh`
- `tools/runner/origin-path-rpi5-audit-dispatcher.sh`
- `tools/hermes_deals_origin_probe.py`

The self-hosted job performs no repository checkout. It may call only the fixed
root-owned dispatcher through sudo.

## Installation

Installation is a separate owner-authorized RPi5 action after the implementation
PR is squash-merged and GitHub CI succeeds.

Create a clean detached worktree at the exact merged `main` SHA. Do not use or
switch `/home/andris/hermes-deals`.

Example:

```bash
sudo tools/runner/install-origin-path-rpi5-audit.sh \
  /home/andris/hermes-deals-worktrees/origin-path-audit-install \
  <exact-merged-main-sha>
```

The installer verifies:

- exact clean detached Git HEAD;
- the commit is reachable from `origin/main`;
- the primary production worktree is not used;
- Python and Bash syntax;
- root-owned installed files and configuration;
- a sudoers rule limited to the fixed dispatcher.

The installer does not run the workflow or probe.

## Workflow execution

Run **Hermes Deals origin path RPi5 audit** manually with:

- `pr_number`: the merged PR that registered the installed audit;
- `as_of`: an explicit canonical `YYYY-MM-DD` date.

Authorization fails closed unless the actor is the allowlisted repository owner,
the PR is merged into `main`, its merge SHA remains reachable from current
`main`, and every required audit file exists in that exact tree.

The fixed targets are:

- public: `https://deals.rozkalns.net`;
- local origin: `http://192.168.0.180:9128`;
- local `Host` header: `deals.rozkalns.net`;
- timeout: 5 seconds;
- no automatic retries.

## Evidence

The uploaded artifact contains only:

- `probe-report.json`;
- `dispatcher-manifest.json`;
- `audit-exit-code.txt`.

The dispatcher revalidates the report and preserves only the probe's allowlisted
headers and structured problem fields. Raw response bodies, cookies,
authorization headers, arbitrary environment data and service logs are not
copied.

Exit codes:

- `0`: all public and origin probes are healthy;
- `1`: degraded public-path, local-probe or mixed classification;
- `2`: edge/tunnel or origin/application failure classification.

A failed or degraded classification intentionally fails the RPi5 job while
still uploading the sanitized artifact.

## Removal

Removal is a separate owner-authorized RPi5 action:

```bash
sudo tools/runner/install-origin-path-rpi5-audit.sh --remove
```

Removal deletes only the audit's dispatcher, installed probe, registration and
sudoers entry. It does not restart Hermes Deals or change production data.

## Not included in this slice

This workflow does not collect `journalctl`, Docker, nginx, cloudflared, CPU,
memory, disk or OOM logs. A later issue #44 slice must define a separate,
strictly sanitized root-cause log evidence contract.
