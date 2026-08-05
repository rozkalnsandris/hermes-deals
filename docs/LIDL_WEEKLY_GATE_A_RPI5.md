# Lidl weekly automation — Gate A on RPi5

Issue: #24

## Purpose

This gate connects the deterministic Lidl weekly shadow controller to the real selected-store discovery and authoritative immutable corpus on RPi5. It remains a read-only operational audit. It does not activate unattended weekly production.

Gate A answers one question for an exact owner-authorized request:

- `READY` — a new exact source/parser/scan/review-profile identity needs a shadow execution and later immutable snapshot handling;
- `NO_OP` — the exact identity matches a previously completed Gate A manifest;
- `WAIT` — the source, authoritative scan, or reviewed profile is not available yet;
- `BLOCKED` — source/parser drift or a trust-boundary violation was detected.

## Runtime boundary

The installer builds one exact-SHA audit image from the repository's pinned `backend/Dockerfile` and records the immutable Docker image ID. The live audit container:

- runs from that exact image ID;
- mounts `/home/andris/hermes-deals-audit-source` at `/repo` read-only;
- mounts `/home/andris/hermes-deals-lidl-corpus` at `/corpus` read-only;
- mounts only its private evidence directory read-write;
- uses `--read-only`, `--cap-drop ALL`, `no-new-privileges`, a PID limit, memory/CPU limits, and the `andris` UID/GID;
- receives no production database URL, Compose environment, Review credential, production volume, or systemd access.

The default bridge network is used only for official Lidl source discovery. No database or Hermes Deals service network is attached.

## GitHub authorization

`.github/workflows/lidl-weekly-gate-a-rpi5.yml` is manual `workflow_dispatch` only. It requires:

- the allowlisted repository owner login and numeric GitHub ID;
- a PR already squash-merged into this repository's `main`;
- the exact merge SHA to remain reachable from current `main`;
- `target=current|next`;
- one canonical `YYYY-MM-DD` Berlin date;
- `use_previous=true|false`.

The self-hosted runner has no Docker-group membership. It may call only the fixed root-owned Gate A dispatcher through the narrow sudo rule. The dispatcher validates every argument, the registered script SHA, image ID, runner temporary directory, output schema, safety flags, and state/exit-code contract.

## Evidence

The retained RPi5 evidence root is:

```text
/home/andris/hermes-deals-lidl-gate-a-evidence
```

The GitHub artifact intentionally contains only:

- `gate-a-summary.json`;
- `safety-result.txt`;
- `run-request.txt`;
- `runner-exit-code.txt`;
- `dispatcher-evidence-manifest.json`.

It does not upload the source PDF, source JSON, discovery capture, full one-shot evidence, completeness rows, or execution log.

## First exact run

After the implementation PR is merged, use the GitHub-tracked owner finalizer with:

- the exact squash-merge SHA;
- that merged PR number;
- `current`;
- the explicit Berlin date of execution;
- `false` for `use_previous`.

A clean `READY` result becomes the first Gate A weekly shadow observation. `WAIT` is also an expected observable state when the official source, scan, or reviewed profile is not ready. `BLOCKED` fails the workflow closed.

## Deterministic no-op replay

After a completed `READY` observation, repeat the same exact request with `use_previous=true`. The runner may select only a structurally valid previous `READY` or `NO_OP` manifest with every write-authority flag disabled. An identical fingerprint must return `NO_OP`; a changed source, parser, scan, or review profile must return `READY` again.

## Safety contract

Every result requires:

- corpus write: false;
- production database write: false;
- Review write/approval: false;
- production publication: false;
- production deployment: false;
- systemd change: false;
- bounded automatic retry: false;
- primary B15M2 worktree unchanged;
- protected B15M2 V08 file unchanged;
- isolated audit clone and both Git indexes unchanged by the audit.

## Gate B

Gate B begins only after Gate A is merged and its exact-SHA RPi5 workflow is verified. Gate B will retain two consecutive real weekly family observations, promote only separately reviewed immutable source evidence, and prove reproducible shadow execution. It will still not authorize production writes.

Production canary, replay against production persistence, timer installation, retry policy, monitoring, rollback, and activation remain later separately owner-authorized gates.
