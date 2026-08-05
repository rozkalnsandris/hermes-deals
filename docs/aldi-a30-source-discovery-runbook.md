# ALDI A3.0 GitHub source-discovery audit

This runbook moves the ALDI current/preview source-discovery loop from manually transferred scripts to the existing controlled RPi5 GitHub Actions audit runner.

The merge does not install or execute the audit. Installation and execution remain separate owner-authorized steps after the implementation pull request is reviewed, CI passes, and the exact merge SHA is known.

## Scope

The audit performs **source discovery only**:

- opens the official ALDI Nord overview and canonical current/preview detail pages;
- records first-party HTTP, lightweight Chromium, iframe, shadow-DOM and network evidence;
- rejects malformed URL candidates, including bracketed invalid IPv6-like strings, without aborting the run;
- recognizes only `magazine.aldi-nord.de` and `ipaper.ipapercms.dk` source paths;
- verifies a candidate only when pages 1 and 2 return plausible image bodies;
- requires distinct verified current and preview source paths for PASS.

It does not perform full page acquisition or the 41/41 rollover comparison.

## Safety boundaries

- No production database write.
- No production deployment, service restart or collector execution.
- No Review action, approval or publication.
- No Docker socket or Docker group access for `github-runner`.
- No checkout or execution of unmerged PR-head code on the self-hosted runner.
- The root-owned installed audit script is bound to one exact merged `main` SHA and SHA256.
- The isolated audit repository and the primary worktree Git indexes must remain unchanged.
- Only sanitized JSON, PNG and log evidence beneath the private staging directory is uploaded.

## One-time installation after merge

Synchronize the isolated audit repository to the exact squash-merge SHA without changing `/home/andris/hermes-deals`, then run:

```bash
cd /home/andris/hermes-deals-audit-source
MERGE_SHA="$(git rev-parse HEAD)"
sudo bash tools/runner/install-aldi-a30-source-discovery-dispatcher.sh "$MERGE_SHA"
```

Required final markers include:

```text
INSTALL_RESULT=PASS
AUDIT=aldi-a30-source-discovery
REGISTERED_COMMIT=<merge-sha>
RUNNER_HAS_DOCKER_GROUP=false
PRIMARY_WORKTREE_MODIFIED=false
PRODUCTION_APPLY_AUTHORIZED=false
```

## Run from GitHub

Open the Actions tab, select **ALDI A3.0 source discovery RPi5**, choose `workflow_dispatch`, and enter the merged registration pull-request number.

The workflow accepts only:

- actor `rozkalnsandris` with numeric GitHub ID `277435981`;
- a pull request already merged into this repository's `main`;
- the exact merge commit still reachable from current `main`;
- a tree containing all registered audit files.

The job runs on the existing labels:

```text
self-hosted
Linux
ARM64
hermes-deals-audit
```

The artifact contains the dispatcher log, sanitized discovery report, optional screenshots, rejected malformed URL candidates and a dispatcher evidence manifest.

A controlled `blocked` discovery result is an evidence-complete execution, not a production failure. Full acquisition remains disabled until current and preview both pass the two-page probe and have distinct source paths.
