# VS Code controlled RPi5 release

Use these tasks only from the RPi5 Remote SSH window with the primary repository `/home/andris/hermes-deals` open on clean synchronized `main`.

## Normal workflow

1. Run `Hermes Deals: Check deploy`.
2. Review the cumulative release range from the running production SHA to exact current `origin/main`.
3. If the check reports `NO DEPLOY NEEDED`, stop. Nothing should be changed in production.
4. If a deploy is required and separately authorized, run `Hermes Deals: Production deploy`.
5. The production task reruns the read-only preflight, prints the exact target SHA and requires the literal confirmation `DEPLOY <40-character SHA>`.
6. Only after that exact confirmation does the guarded direct-main deploy helper run.
7. Review the final API/UI/container checks and keep the timestamped local log path printed by the task.

## Safety boundaries

`Hermes Deals: Check deploy` is read-only. It refuses the wrong repository path, a dirty worktree, a branch other than `main`, unsynchronized local/remote main, a target without successful exact-main CI, unresolvable production provenance, unsafe cumulative Compose changes, or migration state that cannot be reconciled without a database write.

The current direct-main launcher derives the production SHA from the running release-bound API image. It prefers the exact 40-character `org.opencontainers.image.revision` label and falls back only to a canonical `hermes-deals-api:release-<semver>-<sha7>` tag when the OCI revision is absent. Malformed, contradictory or unresolved provenance fails closed.

A cumulative migration change is accepted only when every change is a newly added Alembic revision and the live production `alembic_version` already equals the exact target head. The launcher never runs `alembic upgrade`, `alembic downgrade` or another migration command, and the live Alembic revision must remain unchanged across an API/UI deploy.

The production task is a thin confirmation-and-audit wrapper around the same guarded launcher. It does not bypass any existing release gate. It requires the exact SHA-bound typed confirmation and then calls the existing root-owned runtime-sync and direct-main deploy helpers through the guarded launcher.

## Deploy logs

Each `Hermes Deals: Production deploy` run writes a timestamped log under:

`$XDG_STATE_HOME/hermes-deals/deploy/`

or, when `XDG_STATE_HOME` is not set:

`~/.local/state/hermes-deals/deploy/`

The directory is created with mode `0700` and the log file with mode `0600`. The log records the read-only preflight, target SHA, successful confirmation match, guarded deploy output, final API container running state, exact deployed OCI revision and completion timestamp.

The task does not put logs inside the Git worktree, so a normal deploy does not dirty `/home/andris/hermes-deals`.

## When deploy is not required

Do not deploy merely because a PR was merged. Run `Hermes Deals: Check deploy` after merges that may affect the RPi5 runtime. If production already matches current `main`, or if the merged change is documentation/metadata that does not require a runtime refresh, stop at the check result.

A merge never authorizes a production deployment or a production database write. B15M2 V08 remains outside this workflow unless it is separately and explicitly authorized.
