# EDEKA live Gate C provenance derivation

Issue #26 uses an owner-only GitHub Actions workflow to convert one already successful EDEKA Patzer RPi5 shadow-cycle artifact into sanitized live Gate C provenance evidence.

## Why derive instead of recollect

The authoritative shadow artifact already contains immutable raw HTML, source manifest, isolated SQLite, normalization report, replay evidence and safety evidence. Re-fetching EDEKA would create a different observation and weaken the binding to the audited cycle. The derivation workflow therefore performs no network request to EDEKA and no RPi5 action.

## Input

The manual workflow accepts only `source_run_id`. Authorization then requires:

- owner actor `rozkalnsandris` / actor ID `277435981`;
- dispatch from `main`;
- the referenced run is the successful manual `EDEKA shadow cycle RPi5 audit` in this repository;
- the source run was owner-triggered from `main`;
- exactly one non-expired artifact matches `edeka-shadow-cycle-<registered SHA>-run-<run id>`;
- GitHub exposes a SHA256 metadata digest for that artifact.

The artifact ID, name, digest, source run attempt and registered SHA are passed to the derivation job from GitHub API metadata rather than from user-supplied fields.

## Verification chain

`tools/edeka_live_provenance_derivation.py` fails closed unless all of the following bind:

1. top-level runner request, source run ID/attempt and registered SHA;
2. runner exit code `0`;
3. dispatcher manifest, sanitization result and production-apply=false;
4. inner archive name, bytes, SHA256, sidecar SHA256 and exact member count;
5. no absolute paths, parent traversal, symlinks, hardlinks, devices, FIFOs or unsupported tar members;
6. inner registered commit and capture exit code;
7. worktree/index/production/deploy/scheduler safety evidence;
8. inner and cycle `SHA256SUMS`;
9. sanitized cycle/normalization copies exactly equal the immutable archive copies;
10. the merged live-provenance bridge validates every offer against exact Patzer HTML-card provenance;
11. the existing Gate C validator accepts the derived payload and keeps `promotion_ready=false`.

The workflow also requires the merged bridge origin commit `71ce804f9b9e2a0e7810fa1f035cb6e27592f45f` to be an ancestor of the exact derivation commit.

## Sanitized output

Only four files are uploaded:

- `edeka-live-candidate-provenance.json`;
- `derivation-attestation.json`;
- `SHA256SUMS`;
- `edeka-live-provenance-result.json`.

The extracted raw HTML, SQLite database and source archive are not part of the upload paths. They exist only in the hosted runner's temporary workspace and disappear with that runner.

The attestation records the source workflow/artifact metadata, registered source commit, inner archive hash, cycle evidence hash, exact derivation commit, provenance hash, candidate/route counts and all false production-authority flags.

## Current first-cycle run

The first intended source is shadow workflow run `31157650948`, whose authoritative artifact ID is `8985771511`. The workflow input defaults to that run ID for the first derivation. Future weekly cycles can reuse the same workflow by supplying the new successful shadow-cycle run ID.

## Safety boundary

This workflow does not collect EDEKA, write PostgreSQL or Review state, approve or publish offers, deploy production, activate a scheduler, run a production canary or authorize B15M2 work. A production apply remains a separate explicit decision.
