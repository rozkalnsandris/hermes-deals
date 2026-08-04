# RPi5 GitHub audit runner

This runbook defines the controlled path from GitHub to a sanitized audit artifact produced on the Hermes Deals Raspberry Pi 5.

The design does **not** use an OpenAI API key and does **not** authorize production deployment.

## Components

- Repository-level GitHub Actions runner: `rpi5-hermes-deals-audit`
- Required runner label: `hermes-deals-audit`
- systemd service: `actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service`
- Workflow: `.github/workflows/rpi5-audit-command.yml`
- Polling labels: `audit:runner-smoke` and `audit:b15m2-v08`
- Root-owned dispatcher: `/usr/local/sbin/hermes-deals-audit-dispatch`
- Root-only registration command: `/usr/local/sbin/hermes-deals-audit-register`
- Root-owned audit registry: `/etc/hermes-deals-audits.d`
- Root-owned approved audit copies: `/usr/local/libexec/hermes-deals-audits`

The `github-runner` account must not belong to the `docker` group. It receives passwordless sudo access only to the fixed root-owned dispatcher command.

## Trigger priority

The workflow supports three controlled trigger paths.

### 1. Primary: `workflow_dispatch`

Use the GitHub Actions **Run workflow** button or GitHub CLI.

```bash
gh workflow run rpi5-audit-command.yml \
  --ref main \
  -f audit=runner-smoke \
  -f pr_number=3
```

The caller supplies only an allowlisted audit name and a merged pull-request number. The workflow resolves the exact merge commit SHA from GitHub and verifies that it remains reachable from current `main`.

To inspect recent runs:

```bash
gh run list \
  --workflow rpi5-audit-command.yml \
  --limit 10
```

### 2. External automation: `repository_dispatch`

The workflow accepts only the custom event type `rpi5-audit`.

An owner-authenticated example:

```bash
gh api \
  --method POST \
  repos/rozkalnsandris/hermes-deals/dispatches \
  -f event_type=rpi5-audit \
  -F 'client_payload[audit]=runner-smoke' \
  -F 'client_payload[pr_number]=3'
```

The default allowed dispatch identity is the repository owner:

- login: `rozkalnsandris`
- numeric GitHub ID: `277435981`

A future dedicated GitHub App or connector may be allowlisted with these repository variables after its identity has been independently verified:

```text
HERMES_AUDIT_DISPATCH_LOGIN
HERMES_AUDIT_DISPATCH_ID
```

The workflow still validates the audit name, merged pull request, exact merge SHA, and current `main` ancestry. Client payload data is never trusted as a commit SHA.

### 3. Fallback: scheduled label polling

Every five minutes, offset from the top of the hour, the workflow checks for one pending owner-applied audit label:

```text
audit:runner-smoke
audit:b15m2-v08
```

The polling path verifies the latest matching label event in the pull-request issue history. The latest matching event must be `labeled`, and its actor must be exactly `rozkalnsandris` with numeric GitHub ID `277435981`.

Only one pending audit is selected per workflow run. After the result comment is posted, the polling label is removed automatically. A scheduled run with no valid pending label exits successfully without contacting the RPi5 runner.

Scheduled execution is a fallback, not the primary trigger. GitHub may delay scheduled jobs.

## Trust model

An audit reaches the RPi5 only when all of the following are true:

1. The trigger is `workflow_dispatch`, `repository_dispatch` with event type `rpi5-audit`, or the scheduled polling job.
2. The resolved audit name is exactly `runner-smoke` or `b15m2-v08`.
3. A direct trigger actor matches the configured exact login and numeric GitHub ID.
4. A polling label's latest matching issue event was created by the exact repository owner identity.
5. The pull request is merged into this repository's `main` branch.
6. The workflow obtains the exact merge commit SHA from the GitHub pull-request API.
7. The merge commit remains reachable from current `main`.
8. The root-owned dispatcher accepts the audit name and commit binding.

The self-hosted job does not check out or execute repository code. It calls a root-owned dispatcher. Except for the built-in `runner-smoke` check, an audit can run only after a human administrator registers an immutable root-owned copy from a clean local `main` checkout.

Registration binds three values:

- audit name;
- merged Git commit SHA;
- SHA256 of the installed root-owned audit script.

A compromised `github-runner` account therefore cannot replace the registered audit script, select arbitrary repository code, or use the dispatcher to run a different commit.

## One-time dispatcher installation

Run only after the infrastructure pull request has passed CI and has been squash-merged into `main`:

```bash
cd /home/andris/hermes-deals
git switch main
git pull --ff-only origin main
git status --short

sudo bash tools/runner/install-rpi5-audit-dispatcher.sh
```

The final output must include:

```text
INSTALL_RESULT=PASS
SUDOERS_VALID=true
RUNNER_HAS_DOCKER_GROUP=false
```

Verify independently:

```bash
systemctl is-active actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service
id -nG github-runner
sudo -l -U github-runner
sudo visudo -cf /etc/sudoers.d/hermes-deals-audit-runner
```

Expected conditions:

- the runner service is `active`;
- `github-runner` is not a member of `docker`;
- sudo permits only `/usr/local/sbin/hermes-deals-audit-dispatch`;
- the sudoers file validates successfully.

## Smoke test

Primary smoke test:

```bash
gh workflow run rpi5-audit-command.yml \
  --ref main \
  -f audit=runner-smoke \
  -f pr_number=3
```

Fallback smoke test:

1. Apply `audit:runner-smoke` to merged PR `#3`.
2. Wait for the next polling run.
3. Confirm that the result comment is posted and the label is removed.

The workflow must:

- authorize the request on a GitHub-hosted runner;
- resolve merged PR `#3` to its exact merge commit;
- run the root-owned built-in smoke audit on `rpi5-hermes-deals-audit`;
- upload an artifact named `runner-smoke-<sha>-run-<run-id>`;
- include `runner-smoke.json`, dispatcher log, request metadata, and exit-code evidence;
- report `production_apply_authorized=false`.

## Registering B15M2 V08

Registration is performed only after the V08 script has passed PR review and CI, has been squash-merged, and local `main` is clean at the exact merge SHA:

```bash
cd /home/andris/hermes-deals
git switch main
git pull --ff-only origin main
V08_SHA="$(git rev-parse HEAD)"

git status --short
sudo /usr/local/sbin/hermes-deals-audit-register \
  b15m2-v08 \
  "$V08_SHA" \
  /home/andris/hermes-deals
```

The registration output records the commit SHA, installed script path, and script SHA256. The registration command itself is not granted to `github-runner` through sudo.

Primary V08 trigger:

```bash
gh workflow run rpi5-audit-command.yml \
  --ref main \
  -f audit=b15m2-v08 \
  -f pr_number=<V08_MERGED_PR_NUMBER>
```

Fallback V08 trigger: apply `audit:b15m2-v08` to the merged V08 pull request.

The V08 script must honor this execution contract:

```text
HERMES_AUDIT_TRIGGER=github-actions
HERMES_AUDIT_EXPECTED_BRANCH=main
HERMES_AUDIT_EXPECTED_HEAD=<registered merge SHA>
HERMES_AUDIT_EXPORT_DIR=<private staging directory>
```

Only sanitized evidence written beneath `HERMES_AUDIT_EXPORT_DIR` is eligible for artifact upload.

## Evidence restrictions

Before upload, the dispatcher rejects:

- symlinks, hard links, devices, and FIFOs;
- absolute or parent-traversing archive paths;
- secret-material filenames such as `.pgpass`, `.password`, `.pem`, `.key`, `.env`, or `production.dump`;
- common private-key, GitHub-token, password-URL, `PGPASSWORD`, and command-token patterns;
- evidence larger than 250 MiB.

The production database dump and generated credentials must stay on RPi5 and must never be placed in `HERMES_AUDIT_EXPORT_DIR`.

Artifacts are retained for 14 days. They contain the sanitized audit evidence, dispatcher manifest, runner request metadata, dispatcher log, and exit codes.

## Concurrency and failure behavior

The workflow uses a single repository-wide concurrency group and does not cancel an in-progress audit. Only one RPi5 audit can run at a time.

The scheduled fallback selects at most one pending label per run. Conflicting approved labels on the same PR are ignored until a human leaves exactly one approved label.

The system fails closed when:

- a direct trigger actor is not allowlisted;
- a repository-dispatch event type is not exact;
- the audit is not allowlisted;
- the pull request is not merged into `main`;
- the merge SHA cannot be resolved from GitHub;
- the merge SHA is no longer reachable from current `main`;
- a polling label was not last applied by the exact repository owner;
- the audit is not registered;
- the registered script SHA has drifted;
- evidence contains unsafe members or likely secret material;
- the audit creates no exportable evidence.

A failed dispatcher still uploads the runner log and exit-code evidence when possible.

## Removing the integration

Stop and remove the runner using GitHub's runner removal procedure before deleting its local files. To remove only the privileged dispatcher layer:

```bash
sudo rm -f /etc/sudoers.d/hermes-deals-audit-runner
sudo rm -f /usr/local/sbin/hermes-deals-audit-dispatch
sudo rm -f /usr/local/sbin/hermes-deals-audit-register
sudo rm -rf /etc/hermes-deals-audits.d
sudo rm -rf /usr/local/libexec/hermes-deals-audits
sudo visudo -c
```
