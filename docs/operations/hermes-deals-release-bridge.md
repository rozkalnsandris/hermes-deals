# Hermes Deals no-agent release bridge

This bridge connects the GitHub-first workflow to the controlled RPi5 API/UI
release path from issue #21.

- ChatGPT works through GitHub issues, branches, pull requests and CI.
- GitHub remains the authorization and evidence source of truth.
- Hermes no-agent cron polls every five minutes and runs one fixed script.
- The script invokes one root-owned bridge through an exact sudo rule.
- The existing dedicated release runner performs plan/apply and uploads evidence.

Normal polling makes no model call and uses no tokens. Empty stdout is a silent
Hermes tick. Hermes never diagnoses, edits, invents commands or retries an
alternative action.

## Persistent GitHub token

Create one fine-grained personal access token restricted to
`rozkalnsandris/hermes-deals` with only:

- Actions: read and write;
- Issues: read and write;
- Pull requests: read;
- Contents: read;
- Metadata: read.

It is installed at `/etc/hermes-deals-release-bridge/token` as `root:root` mode
`0600`. It is never stored in GitHub, Hermes prompts, cron definitions, artifacts
or command-line arguments.

Runner registration is separate. The bootstrap uses the existing owner-authenticated
`gh` installation on the RPi5 to request GitHub's temporary runner registration
token. The persistent bridge token does not need repository administration.

## One-time installation

Run only after this bridge PR is squash-merged and exact-main CI is green. The
primary worktree is fetched but never switched, reset, stashed or cleaned.

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

Expected evidence:

```text
BOOTSTRAP_RESULT=PASS
RUNNER_HAS_DOCKER_GROUP=false
RELEASE_DISPATCHER_INSTALLED=true
HERMES_BRIDGE_INSTALLED=true
HERMES_CRON_JOB=hermes-deals-release-bridge
HERMES_NO_AGENT=true
DATABASE_WRITES_AUTHORIZED=false
```

The bootstrap validates the token, creates the five `hermes:deploy-*` labels,
installs the SHA-verified ARM64 Actions runner, keeps it outside the Docker group,
creates the detached `release-control` worktree, installs the existing controlled
release tools and creates the Hermes script-only cron job.

## Deploy request contract

ChatGPT creates a separate owner-authored issue. Its title starts with
`[Hermes deploy]`, it has `hermes:deploy-ready`, and its body contains exactly
one marker and one JSON object:

````markdown
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
````

Required invariants:

- the source PR must be squash-merged to `main`;
- the SHA must equal the PR merge SHA and exact current `main`;
- exact-main push CI must be successful;
- request author login and immutable numeric ID must match the owner;
- no extra or missing JSON fields are allowed;
- only `smoke/plan`, `api-ui/plan` and `api-ui/apply` are accepted;
- database writes must explicitly remain false;
- B15M2 issue #20 remains explicitly rejected.

## Execution

For `api-ui`, root-only auto-registration updates only the detached worktree,
verifies PR/main/CI, derives the tracked FastAPI version, binds the current image
as rollback, creates a root-owned rollback archive, and invokes the existing
register tool. That tool builds the exact target image, runs its complete test
suite and creates an immutable release registry entry.

The bridge first dispatches `plan` and requires the expected non-empty sanitized
artifact. For an apply request, only after plan PASS, it dispatches `apply` with
the exact authorization phrase. The existing controlled dispatcher changes only
the API service, verifies image identity, health, UI and unchanged Alembic
revision, and performs its already-defined automatic rollback if the canary fails.

PASS closes the deploy request with `hermes:deploy-pass`. Workflow failure adds
`hermes:deploy-fail`. Validation or registration refusal adds
`hermes:deploy-blocked`. Hermes performs no alternative attempt.

## Checks

```bash
hermes cron list
hermes cron status
sudo --non-interactive /usr/local/sbin/hermes-deals-release-bridge poll
systemctl status \
  actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service
id -nG github-release-runner
sudo -l -U github-release-runner
sudo -l -U andris
```

## Explicitly blocked work

The bridge does not authorize or implement:

- database migration or production data write;
- broad Review approval or publication;
- Compose configuration change;
- Cloudflare, DNS, token or secret changes;
- later host, systemd or Docker infrastructure changes;
- destructive deletion or owner-requested rollback;
- B15M2 issue #20.

These remain separate, explicitly owner-authorized workflows.

## Removal

Pause/remove the Hermes cron job and use GitHub's official runner removal flow.
Then remove only the bridge layer:

```bash
sudo rm -f /etc/sudoers.d/hermes-deals-release-bridge
sudo rm -f /usr/local/sbin/hermes-deals-release-bridge
sudo rm -f /usr/local/sbin/hermes-deals-release-auto-register
sudo rm -rf /etc/hermes-deals-release-bridge
sudo rm -rf /var/lib/hermes-deals-release-bridge
sudo rm -f /home/andris/.hermes/scripts/hermes-deals-release-bridge.sh
sudo visudo -c
```

Release and rollback archives require separate retention review.
