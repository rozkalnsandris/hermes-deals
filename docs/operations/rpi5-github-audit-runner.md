# RPi5 GitHub audit runner

This runbook defines the controlled path from an owner-authored GitHub pull-request comment to a sanitized audit artifact produced on the Hermes Deals Raspberry Pi 5.

The design does **not** use an OpenAI API key and does **not** authorize production deployment.

## Components

- Repository-level GitHub Actions runner: `rpi5-hermes-deals-audit`
- Required runner label: `hermes-deals-audit`
- systemd service: `actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service`
- Workflow: `.github/workflows/rpi5-audit-command.yml`
- Root-owned dispatcher: `/usr/local/sbin/hermes-deals-audit-dispatch`
- Root-only registration command: `/usr/local/sbin/hermes-deals-audit-register`
- Root-owned audit registry: `/etc/hermes-deals-audits.d`
- Root-owned approved audit copies: `/usr/local/libexec/hermes-deals-audits`

The `github-runner` account must not belong to the `docker` group. It receives passwordless sudo access only to the fixed root-owned dispatcher command.

## Trust model

The workflow runs only when all of the following are true:

1. The event is a newly created comment on a pull request.
2. The commenter is exactly `rozkalnsandris` with GitHub author association `OWNER`.
3. The command exactly matches `/run <approved-audit> <40-character-sha>`.
4. The pull request is merged into this repository's `main` branch.
5. The requested SHA is exactly that pull request's merge commit SHA.
6. The requested SHA remains reachable from current `main`.
7. The requested audit name is workflow-allowlisted.

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

After the workflow and installer are merged and the dispatcher is installed, comment on the merged infrastructure pull request:

```text
/run runner-smoke <INFRASTRUCTURE_SQUASH_MERGE_SHA>
```

The workflow must:

- authorize the comment on a GitHub-hosted runner;
- run the root-owned built-in smoke audit on `rpi5-hermes-deals-audit`;
- upload an artifact named `runner-smoke-<sha>-run-<run-id>`;
- include `runner-smoke.json`, the dispatcher log, request metadata, and exit-code evidence;
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

Then comment on the merged V08 pull request:

```text
/run b15m2-v08 <V08_SQUASH_MERGE_SHA>
```

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

The system fails closed when:

- the comment syntax is not exact;
- the commenter is not the repository owner;
- the pull request is not merged into `main`;
- the SHA is not the merged PR commit;
- the audit is not allowlisted or registered;
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
