# VS Code controlled RPi5 release

Use these tasks only from the RPi5 Remote SSH window with the primary repository `/home/andris/hermes-deals` open on clean synchronized `main`.

1. Run `Hermes Deals: Check deploy`.
2. Review the cumulative release range from the running production SHA to exact current `main`.
3. Run `Hermes Deals: Plan production deploy` and require the bridge request to finish with `hermes:deploy-pass`.
4. Review the GitHub issue, workflow result and sanitized evidence.
5. Run `Hermes Deals: Apply production deploy` only after explicit owner approval and type the exact SHA-bound confirmation shown in the terminal.

The launcher derives the current production SHA from the release-bound API image and checks the complete cumulative diff to current `main`, not only the latest PR. It prefers the exact 40-character `org.opencontainers.image.revision` label, which also supports previously verified legacy release tag names. Only when that label is absent may it fall back to the canonical `hermes-deals-api:release-<semver>-<sha7>` tag. Malformed, contradictory or unresolved provenance fails closed.

It refuses dirty worktrees, non-main branches, another repository path, unsynchronized local/remote main, a current main commit not bound to exactly one merged PR, unresolved source issues and cumulative Compose changes.

A cumulative migration change remains blocked by default. The only exception is a schema-already-applied reconciliation: every migration change must be a newly added Python revision under `backend/alembic/versions/`, the target migration graph must have exactly one head, and the live production `alembic_version` must already equal that exact target head. Changes to `alembic.ini`, deleted or modified revisions, alternate migration directories, multiple heads, missing database identity or a different live schema version fail closed. This reconciliation performs no migration command and never authorizes a database write.

Plan and apply create owner-authored `hermes:deploy-ready` requests for the existing no-agent release bridge. The bridge performs root auto-registration, exact-main CI verification, immutable image build and testing, plan evidence, apply authorization, API-only recreation, health/UI checks and automatic rollback. A verified legacy running image is assigned a canonical rollback alias using its exact OCI revision and historical application version; the running container is not changed during plan.

The root-owned dispatcher reads `alembic_version` directly from PostgreSQL before and after API replacement and requires the value to remain identical. It never runs `alembic upgrade` or another migration command. The release runtime installer updates the dispatcher, register, bridge and auto-register components together from the detached exact-`origin/main` release-control worktree.

`Check deploy` is read-only. `Plan production deploy` registers and verifies the exact cumulative release without applying production. `Apply production deploy` is the only task that may change production.
