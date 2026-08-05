# Hermes Deals no-agent release bridge

This runbook connects the GitHub-first development workflow to the controlled
RPi5 release path added by issue #21.

The design keeps responsibilities separate:

- ChatGPT works through GitHub issues, branches, pull requests and CI;
- GitHub remains the authorization and evidence source of truth;
- Hermes no-agent cron polls every five minutes and runs one fixed script;
- the script invokes one root-owned bridge through an exact sudo rule;
- the bridge validates a machine-readable owner-authored GitHub request;
- the existing controlled workflow performs plan/apply through the dedicated
  `github-release-runner` account;
- sanitized workflow artifacts and comments return the result to GitHub.

Normal polling makes no model call and uses no tokens. Empty script output is a
silent Hermes cron tick. Hermes does not diagnose, edit, retry an alternative,
or construct shell commands.

## Persistent GitHub token

Create one fine-grained personal access token restricted to
`rozkalnsandris/hermes-deals` with only:

- Actions: read and write;
- Issues: read and write;
- Pull requests: read;
- Contents: read;
- Metadata: read.

The token is installed as `/etc/hermes-deals-release-bridge/token`, owned by
`root:root` with mode `0600`. It is never stored in GitHub, Hermes prompts,
cron definitions, artifacts or command-line arguments.

Runner registration is deliberately separate. The bootstrap uses the existing
owner-authenticated `gh` installation on the RPi5 to obtain GitHub's temporary
runner registration token. The persistent bridge token is not granted repository
administration permission.

## One-time installation

Run only after the bridge PR is squash-merged and its exact `main` CI is green.
The primary worktree is fetched but never switched, reset, stashed or cleaned.

```bash
PRIMARY=/home/andris/hermes-deals

git -C "$PRIMARY" fetch origin main
SHA="$(git -C "$PRIMARY" rev-parse refs/remotes/origin/main)"

git -C "$PRIMARY" show \
  "$SHA:tools/runner/bootstrap-hermes-deals-release-runtime.sh" \
  > /tmp/bootstrap-hermes-deals-release-runtime.sh
chmod 700 /tmp/bootstrap-hermes-deals-release-runtime.sh

read -rsp "Hermes GitHub token: " HERMES_GITHUB_TOKEN
echo
export HERMES_GITHUB_TOKEN
sudo --preserve-env=HERMES_GITHUB_TOKEN \
  /tmp/bootstrap-hermes-deals-release-runtime.sh "$SHA"
unset HERMES_GITHUB_TOKEN
rm -f /tmp/bootstrap-hermes-deals-release-runtime.sh
```

Expected final evidence:

```text
BOOTSTRAP_RESULT=PASS
RUNNER_HAS_DOCKER_GROUP=false
RELEASE_DISPATCHER_INSTALLED=true
HERMES_BRIDGE_INSTALLED=true
HERMES_CRON_JOB=hermes-deals-release-bridge
HERMES_NO_AGENT=true
DATABASE_WRITES_AUTHORIZED=false
```

The bootstrap:

1. validates the persistent token identity and repository access;
2. creates the five `hermes:deploy-*` labels if missing;
3. installs a dedicated ARM64 GitHub Actions runner after verifying the release
   asset's published SHA-256 digest;
4. keeps `github-release-runner` outside the Docker group;
5. creates or updates the clean detached `release-control` worktree;
6. installs the already-reviewed controlled release dispatcher/register tools;
7. installs the bridge and root-only auto-register helper;
8. grants `andris` sudo for exactly
   `/usr/local/sbin/hermes-deals-release-bridge poll`;
9. creates a Hermes script-only cron job every five minutes with Telegram
   delivery.

## Deploy request contract

ChatGPT creates a separate GitHub issue authored by the repository owner. Its
title starts with `[Hermes deploy]`, it has label `hermes:deploy-ready`, and its
body contains exactly one marker and one JSON object:

```markdown
<!-- hermes-deals-release-request-v1 -->

```json
{
  "schema_version": 1,
  "repository": "rozkalnsandris/hermes-deals",
  "release_class": "api-ui",
  "source_issue": 44,
  "source_pr": 123,
  "release_sha": "0123456789abcdef0123456789abcdef01234567",
  "mode": "apply",
  "audit_run_id": null,
  "owner_authorized": true,
  "database_writes_authorized": false
}
```
```

Required invariants:

- the source PR must be squash-merged to `main`;
- `release_sha` must equal both the PR merge SHA and exact current `main`;
- exact-main push CI must be successful;
- the request author login and immutable numeric GitHub ID must match the owner;
- the request must contain no extra or missing fields;
- only `smoke/plan`, `api-ui/plan` and `api-ui/apply` are accepted;
- database writes must explicitly remain false;
- B15M2 issue #20 remains explicitly rejected.

## Execution

For `api-ui`, the bridge first creates an immutable root registration:

- updates only the detached `release-control` worktree;
- verifies the source PR, exact current `main` and exact-SHA successful CI;
- derives the numeric FastAPI version from tracked source;
- binds the currently running release image as rollback;
- creates and restore-tests a root-owned rollback archive;
- calls the existing root-only release register, which builds the target image,
  runs the complete test suite inside it and writes an immutable registry entry.

The bridge then dispatches `plan`. It waits through later polling ticks until the
workflow finishes and requires the expected non-empty sanitized artifact.

For an `apply` request, only after plan PASS, it dispatches `apply` with the exact
workflow authorization phrase. The controlled dispatcher recreates only the API
service, confirms image identity, health, UI and unchanged Alembic revision, and
performs the already-defined automatic rollback if its canary fails.

On PASS the deploy request receives `hermes:deploy-pass` and is closed. On
workflow failure it receives `hermes:deploy-fail`. Validation and registration
refusals receive `hermes:deploy-blocked`. Hermes performs no alternative attempt.

## Operations

```bash
# Show the no-agent job and scheduler state
hermes cron list
hermes cron status

# Run one bridge poll manually as the normal user
sudo --non-interactive /usr/local/sbin/hermes-deals-release-bridge poll

# Check the dedicated release runner
systemctl status \
  actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service

# Verify least privilege
id -nG github-release-runner
sudo -l -U github-release-runner
sudo -l -U andris
```

## Explicitly blocked work

This bridge does not authorize or implement:

- database migration or production data write;
- broad Review approval or publication;
- Compose configuration change;
- Cloudflare, DNS, token or secret changes;
- host, systemd or Docker infrastructure changes after installation;
- destructive deletion;
- owner-requested rollback as a normal action;
- B15M2 issue #20.

Those actions remain separate and require explicit owner approval and their own
reviewed fail-closed workflow.

## Removal

Pause/remove the Hermes cron job, remove the dedicated runner through GitHub's
official runner removal flow, then remove only the bridge layer:

```bash
sudo rm -f /etc/sudoers.d/hermes-deals-release-bridge
sudo rm -f /usr/local/sbin/hermes-deals-release-bridge
sudo rm -f /usr/local/sbin/hermes-deals-release-auto-register
sudo rm -rf /etc/hermes-deals-release-bridge
sudo rm -rf /var/lib/hermes-deals-release-bridge
sudo rm -f /home/andris/.hermes/scripts/hermes-deals-release-bridge.sh
sudo visudo -c
```

Do not remove release/rollback archives until their retention has been reviewed
separately.
