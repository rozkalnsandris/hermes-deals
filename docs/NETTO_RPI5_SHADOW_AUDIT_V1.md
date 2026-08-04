# Netto RPi5 shadow evidence audit v1

## Purpose

`netto-shadow-v1` is the first real RPi5 evidence gate after the shadow-only
foundation merged in PR #42. It gathers evidence needed by issues #27 and #28
without deploying code, writing to PostgreSQL, installing the weekly systemd
timer, approving Review rows or publishing offers.

The audit uses the existing self-hosted RPi5 GitHub runner label set, but it has
its own dedicated root-owned dispatcher and sudo rule. B15M2 V08 and the generic
RPi5 audit dispatcher are not modified.

## Read-only inputs

The registered audit reads only these bounded locations:

- `/home/andris/hermes-deals-audits` for immutable Netto AuditRow corpora;
- `/home/andris/hermes-deals/data/raw` for family-primary store `5659`
  manifests and their HTML/PDF bindings;
- `/var/lib/hermes-deals/netto-weekly-shadow` for previously recorded shadow
  transition decisions, when that state directory exists;
- the clean `/home/andris/hermes-deals` `main` checkout at the exact registered
  commit.

It does not read `.env`, database credentials or PostgreSQL data. It never calls
Docker, Compose, `psql`, the API mutation routes or systemd installation
commands.

## Evidence outputs

Only a fixed allowlist of JSON/text files may leave the root-owned dispatcher:

- `audit-summary.json`;
- `corpus-report.json`;
- `evidence-inventory.json`;
- `weekly-decisions.json`;
- `transition-history.json`;
- `audit-artifact-manifest.json`;
- execution log and exit-code files.

The dispatcher rejects symlinks, unexpected filenames, files larger than 32 MiB
and common credential/private-key patterns. Raw HTML, PDFs, database dumps and
source snapshots are never uploaded.

A technically successful audit may report `result=blocked`. That is the correct
result when the real immutable corpus is incomplete, evidence hashes do not
verify, or two actual unattended transition records do not yet exist. A blocked
gate never enables automatic selection or a production write.

## Installation after merge

From a clean, synchronized production checkout at the exact squash-merge SHA:

```bash
cd /home/andris/hermes-deals
sudo bash tools/runner/install-netto-shadow-rpi5-audit.sh <MERGE_SHA>
```

The installer:

- requires `main`, a clean worktree and the exact SHA;
- requires the expected GitHub origin;
- refuses installation if `github-runner` belongs to the Docker group;
- installs immutable root-owned copies of the runner and Python audit tool;
- records both SHA-256 values and the allowed commit in a root-owned config;
- installs one dedicated sudo command only.

## Trigger

After installation, add the exact label `audit:netto-shadow-v1` to the merged PR.
The default-branch `pull_request_target` workflow validates both the owner's
login and numeric GitHub ID, confirms the PR is merged into `main`, and confirms
the merge SHA remains reachable from current `main` before queuing the RPi5
runner.

The workflow checks out no pull-request code. It uploads the sanitized evidence,
posts a machine-readable result comment to the merged PR, and removes the label.

## Issue interpretation

Issue #27 evidence is ready only when a real immutable AuditRow corpus is
successfully evaluated across at least two campaign families. Fields may still
remain Review-only when their independent precision, coverage, sample or
campaign-diversity gate fails.

Issue #28 is not considered complete from simulated decisions alone. The audit
requires two distinct timestamped real transition-history campaign keys with safe
shadow actions and no production-write authorization before setting
`issue_28_two_real_transitions_ready=true`.
