# EDEKA production canary root registration

This document defines the **registration-only** trust boundary that follows merged PR #667.

Registration installs one checksum-bound root dispatcher and one exact-main immutable runtime bundle. It does **not** authorize or execute the EDEKA production canary.

## Why this boundary is narrow

`rozkalnsandris/hermes-deals` is a public repository and the operational bridge uses a self-hosted RPi5 runner. GitHub's secure-use guidance warns that self-hosted runners are not guaranteed clean/ephemeral and may remain compromised after untrusted workflow execution. The privileged side therefore treats every runner-provided value as untrusted and accepts only:

1. one operation: `verify`, `apply`, `replay`, or `rollback`;
2. one exact 40-hex commit SHA;
3. one runner export directory under the fixed GitHub runner temp root.

The runner never supplies repository paths, retained-evidence paths, Docker images, database credentials, SQL, backup paths, authorization JSON, or arbitrary commands.

The sudo project describes its philosophy as granting as few root privileges as possible while still allowing the required work. This registration follows that model with one fixed dispatcher command and an exact argument regex.

References:

- GitHub Actions secure use: `https://docs.github.com/en/actions/reference/security/secure-use`
- sudo upstream: `https://github.com/sudo-project/sudo`

## Source-of-truth inputs

The root installer must be executed later, after merge, from the dedicated EDEKA audit clone:

`/home/andris/hermes-deals-audit-source-edeka`

It requires:

- branch `main`;
- clean worktree and unchanged Git index;
- exact requested `HEAD`;
- exact SHA reachable from `origin/main`;
- allowlisted Hermes Deals origin;
- exact reviewed Git blobs for:
  - `tools/runner/edeka_production_canary_control.py`;
  - `backend/app/edeka_production_canary.py`;
  - `config/edeka-production-canary-v01.json`;
  - `backend/locks/runtime-py313.txt`;
  - `.github/workflows/hermes-edeka-production-canary-control.yml`;
- running installer bytes equal to the installer blob in that exact commit.

The installer materializes `backend/app`, `backend/locks/runtime-py313.txt`, and the canary plan from Git object bytes into an append-only root-owned bundle:

`/usr/local/libexec/hermes-deals-edeka-production-canary-control/<registration-sha>/`

All bundle files are root-owned and read-only. `MANIFEST.json` binds every bundled file by SHA-256.

## Registration artifacts

For one exact registration SHA the installer creates, or verifies identical:

- dispatcher:
  `/usr/local/sbin/hermes-deals-edeka-production-canary-control`
- config:
  `/etc/hermes-deals-audits.d/edeka-production-canary-control/<registration-sha>.json`
- sudoers:
  `/etc/sudoers.d/hermes-deals-edeka-production-canary-control-<registration-sha>`
- immutable runtime bundle:
  `/usr/local/libexec/hermes-deals-edeka-production-canary-control/<registration-sha>/`
- root-only backup directory:
  `/var/lib/hermes-deals/edeka-production-canary-backups`

The registration is append-only per SHA. An existing path with different bytes, owner, mode, or file set fails closed.

The installer also requires:

- Sudo `>= 1.9.10` for regex argument matching;
- `github-runner` not in the Docker group;
- valid `visudo` syntax before and after installation;
- positive sudo policy probes for all four exact operations;
- negative probes for wrong SHA, wrong operation, wrong export path, missing arguments, and extra arguments.

## Dispatcher execution contract

The dispatcher loads only the root-owned config matching the supplied exact SHA.

Before touching the database it verifies:

- full immutable bundle manifest;
- exact plan SHA-256;
- exact runtime-lock SHA-256;
- exactly one running production `api` container and one running `db` container for Compose project `hermes-deals`;
- both services attached only to `hermes-deals_internal`;
- immutable Docker image identity;
- the running API image's `/app/locks/runtime-py313.txt` equals the registered lock;
- exactly one retained EDEKA first-cycle evidence set matching the plan's snapshot, manifest SHA-256, and raw HTML SHA-256.

It does **not** read production `docker-compose.yml` or `.env` as a privileged instruction source.

The canary executor runs in a one-shot container using the currently running production API image only as the dependency/runtime base. The exact reviewed `backend` bundle is mounted read-only and becomes `PYTHONPATH`.

The one-shot container is:

- attached only to `hermes-deals_internal`;
- read-only;
- `--cap-drop ALL`;
- `no-new-privileges`;
- limited to a `noexec,nosuid,nodev` `/tmp`;
- given `DATABASE_URL` through a root-only temporary env file;
- given only read-only canary plan/manifest/raw/authorization mounts.

No raw source or database credential is exported to GitHub.

## Operation semantics

### `verify`

Read-only. It runs the executor in `verify` mode and exports sanitized state/counts only.

### `apply`

Allowed only when pre-verification proves the canary state is `empty`.

Before the executor receives write authorization, the dispatcher:

1. creates a PostgreSQL custom-format backup from the running DB container;
2. verifies that backup with `pg_restore --list`;
3. records the backup SHA-256;
4. creates the exact short-lived owner-authorization JSON with baseline counts from the verified production state.

The backend executor still enforces its own single-transaction +1/+3/+3 delta contract. A post-operation `verify` must prove state `complete` and the exact expected counts.

### `replay`

Allowed only when pre-verification proves state `complete`.

This prevents a replay command from becoming a first apply. The dispatcher derives the original baseline from current counts minus the exact plan delta, creates/verifies a backup, invokes backend `apply`, and requires:

- executor state `replay_noop`;
- `writes_performed=false`;
- post-verification still `complete`;
- no database count changes.

### `rollback`

Allowed only for `empty` or `complete`.

A verified backup is created before authorization. For a complete state, baseline is derived by subtracting the exact canary delta. The backend executor may delete only the deterministic canary snapshot/candidates/normalizations and already rejects dependent matching/review rows. Post-verification must prove state `empty` and exact baseline restoration.

## Sanitized evidence

The root dispatcher creates only `dispatcher-result.json` inside the workflow-created private export directory. It contains:

- operation and exact registered commit;
- plan/manifest identities;
- state and monitored counts;
- whether a write occurred;
- verified backup SHA-256 when applicable;
- hashed executor stderr identity;
- explicit `false` markers for source refetch, Review/publication writes, scheduler/systemd changes, and production deploy.

Raw HTML, manifest contents, authorization JSON, backup bytes/path, database URL/password, Docker inspect payloads, and command stderr are not exported.

## Authorization boundaries

Merging the registration source PR does **not** perform registration.

Later root registration requires a separate explicit owner authorization.

A successful root registration still does **not** authorize:

- `verify`;
- production canary `apply`;
- `replay`;
- `rollback`;
- EDEKA source refetch;
- production DB/Review/publication write outside the exact canary executor;
- scheduler/systemd changes;
- production deploy.

Each canary control operation remains a separate owner command through issue #26 and must bind to the exact current `main` SHA with green exact-main CI.

**Production DB write: NO (registration source / registration itself).**

**Production deploy: NO.**
