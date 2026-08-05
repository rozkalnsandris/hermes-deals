# Controlled GitHub-to-RPi5 API/UI release

This runbook defines the first implementation slice of issue #21. It adds a
manual, owner-authorized path from an exact merged `main` SHA to a registered
immutable Hermes Deals API/UI image on the Raspberry Pi 5.

This repository change **does not install the runner, register an image, deploy
production, or write the production database**.

## Supported release classes

- `smoke`: proves the GitHub authorization, separate release runner, root-owned
  dispatcher and sanitized artifact chain. It can run only in `plan` mode.
- `api-ui`: plans or applies a previously root-registered immutable API image.
  The dispatcher recreates only the `api` service with `--no-deps --no-build`.

Migration and data-write releases are intentionally not included in this slice.
They require a separate issue #21 PR with a backup/restore contract, an exact
migration adapter, an additional owner authorization phrase and a root registry
field that explicitly permits database writes.

## Trust boundaries

The release path is separate from the audit path:

- OS account: `github-release-runner`
- runner label: `hermes-deals-release`
- runner directory: `/home/github-release-runner/actions-runner`
- expected service:
  `actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service`
- sudo allowlist: only `/usr/local/sbin/hermes-deals-release-dispatch`
- root-only registration tool: `/usr/local/sbin/hermes-deals-release-register`
- registry: `/etc/hermes-deals-releases.d`
- release archives: `/opt/backups/hermes-deals/releases`

`github-release-runner` must not belong to the `docker` group. It never receives
sudo access to the registration tool.

The release workflow shares the repository-wide `hermes-deals-rpi5-audit`
concurrency group with the general audit workflow. The separately implemented
Netto shadow audit still has a legacy dedicated group, so release authorization
and the self-hosted release job both query that workflow and fail closed while
it is active. The root dispatcher also refuses when an existing general or Netto
audit dispatcher process is running, then takes its own root release lock before
touching Docker. A later issue #21 slice should migrate every privileged RPi5
workflow to one common mutex; this slice does not claim that migration is done.

## GitHub authorization contract

`.github/workflows/rpi5-release-command.yml` accepts only
`workflow_dispatch`. The GitHub-hosted authorization job rejects the request
unless all conditions hold:

1. the workflow runs from `main`;
2. the actor login and immutable numeric ID match the repository owner;
3. the supplied PR is merged into this repository's `main`;
4. the supplied 40-character SHA is exactly that PR's squash merge SHA;
5. the SHA is exactly current `main`, not merely an old ancestor;
6. an exact-SHA `Hermes Deals CI` push run completed successfully;
7. no dedicated Netto shadow audit workflow run is queued or active;
8. immediately before self-hosted dispatch, current `main` still equals the
   authorized SHA and the dedicated Netto audit is still inactive;
9. an optional issue-specific RPi5 audit run is successful, allowlisted and
   bound to the same exact SHA;
10. `apply` uses the exact phrase `APPLY api-ui <40-character-sha>`.

The authorization phrase is a confirmation string, not a secret. It is not
forwarded to the self-hosted runner or stored in release evidence.

## One-time release runner setup

Create a dedicated local account and install a repository-scoped GitHub Actions
runner under `/home/github-release-runner/actions-runner`. Assign only these
labels in addition to the standard system labels:

```text
hermes-deals-release
```

Do not add the account to `docker`.

After the infrastructure PR is merged and the service is active, install the
root-owned dispatcher layer from a clean exact `main` checkout:

```bash
cd /home/andris/hermes-deals
git switch main
git pull --ff-only origin main
git status --short

sudo bash tools/runner/install-rpi5-release-dispatcher.sh
```

Expected final fields:

```text
INSTALL_RESULT=PASS
SUDOERS_VALID=true
RUNNER_HAS_DOCKER_GROUP=false
DATABASE_WRITES_AUTHORIZED=false
```

Independent checks:

```bash
systemctl is-active \
  actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service
id -nG github-release-runner
sudo -l -U github-release-runner
sudo visudo -cf /etc/sudoers.d/hermes-deals-release-runner
```

## No-op smoke

After installation, run the workflow manually with:

- class: `smoke`
- PR: the merged infrastructure PR
- SHA: that PR's exact squash merge SHA, which must still be current `main`
- mode: `plan`
- audit run ID: empty
- authorization: empty

The run must upload a sanitized artifact containing a release report with:

```text
production_apply_performed=false
database_writes_authorized=false
release_runner_to_dispatcher_contract=true
```

This smoke is required before any image registration.

## Register an API/UI image

Registration is a root-only local operation. It builds the image from a clean
exact `main`, applies an OCI revision label, runs the complete test suite inside
the image, creates a root-owned archive, copies and restore-tests the rollback
archive, and writes an immutable JSON registry entry.

Example:

```bash
cd /home/andris/hermes-deals
git switch main
git pull --ff-only origin main

NEW_SHA="$(git rev-parse HEAD)"
ROLLBACK_SHA="<full-current-production-sha>"
ROLLBACK_TAG="hermes-deals-api:release-<version>-${ROLLBACK_SHA:0:7}"
ROLLBACK_ARCHIVE="/path/to/verified/current-production-image.tar.gz"

sudo /usr/local/sbin/hermes-deals-release-register \
  api-ui \
  "$NEW_SHA" \
  "<new-semver>" \
  "$ROLLBACK_SHA" \
  "$ROLLBACK_TAG" \
  "$ROLLBACK_ARCHIVE" \
  /home/andris/hermes-deals \
  "<required-successful-main-ci-run-id>" \
  "<optional-required-audit-run-id>"
```

Registration must end with:

```text
REGISTER_RESULT=PASS
ROLLBACK_RESTORE_TESTED=true
REQUIRED_CI_RUN_ID=<exact-successful-main-ci-run-id>
DATABASE_WRITES_AUTHORIZED=false
PRODUCTION_APPLY_PERFORMED=false
```

A legacy rollback image may predate OCI revision labels. In that bootstrap
case, registration still binds the full rollback SHA to the running container,
release tag, image ID and copied archive hash, and reports
`ROLLBACK_REVISION_LABEL_VERIFIED=false`. Any contradictory existing label is
rejected. New images always require the exact full-SHA OCI revision label.

Registration takes the same root release lock used by apply and refuses while
an existing audit dispatcher process is active. It does not recreate any service.

## Plan

Run the workflow with class `api-ui`, mode `plan`, the exact registered SHA and
the same optional audit run ID used during registration. Leave authorization
empty.

The dispatcher verifies, without changing production:

- root registry ownership and exact SHA binding;
- clean local `main` at the release SHA;
- new and rollback image IDs, OCI revision labels and archive hashes;
- current API container equals the registered rollback baseline;
- current health response and Alembic revision;
- database writes remain unauthorized.

## Apply

Apply only after reviewing the plan artifact. Run the same workflow inputs with:

- mode: `apply`
- authorization: `APPLY api-ui <exact-release-sha>`

Before promotion, the dispatcher loads the rollback archive and verifies the
expected image ID. It then loads the new archive, recreates only `api`, checks
container image identity, `/api/health`, and `/ui`.

If the new image or canary fails, the dispatcher immediately recreates `api`
with the registered rollback tag and verifies rollback health. A failed apply
remains a failed workflow even when rollback succeeds.

No migration command is run. The dispatcher reports:

```text
database_writes_authorized=false
migration_commands_executed=false
```

## Evidence

Only the root dispatcher's `release-evidence` directory is uploaded. Raw runner
request files and `tee` logs are not artifact inputs. Before upload, the
dispatcher rejects non-regular members, oversized evidence and common
private-key, GitHub-token, database URL and `PGPASSWORD` patterns.

Artifacts are retained for 30 days. The workflow also posts a bounded result
comment on the merged source PR.

## Removal

Stop and remove the dedicated GitHub runner using GitHub's official runner
removal flow. Then remove only the privileged release layer:

```bash
sudo rm -f /etc/sudoers.d/hermes-deals-release-runner
sudo rm -f /usr/local/sbin/hermes-deals-release-dispatch
sudo rm -f /usr/local/sbin/hermes-deals-release-register
sudo rm -rf /etc/hermes-deals-releases.d
sudo visudo -c
```

Do not delete `/opt/backups/hermes-deals/releases` until current and rollback
image retention has been reviewed independently.
