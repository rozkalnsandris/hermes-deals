# Lidl frozen semantic corpus RPi5 audit

This runbook completes the real-corpus verification required by issue #23 after the semantic gate code has been merged.

## Purpose

The audit reads the two immutable Lidl corpus bindings declared in:

`tools/lidl_parser_provenance/v631/manifest.json`

For every binding it:

- locates exactly one complete corpus directory;
- verifies the frozen PDF and raw JSON SHA-256 values;
- extracts the exact registered Git commit with `git archive` into a private temporary directory;
- builds the reviewed semantic view;
- requires every parser row to be assigned to production-ready, Review or excluded;
- requires `unexplained_count == 0`;
- repeats the semantic build and requires byte-identical output;
- exports only sanitized evidence;
- performs no database write, Review seed, approval, publication or production deployment.

## Trust boundary

The GitHub Actions runner does not check out or execute arbitrary repository code.

The root-only installer extracts the audit script from one exact merged commit SHA and installs it as:

`/usr/local/libexec/hermes-deals-audits/lidl-semantic-corpus.sh`

The registration stores:

- audit name;
- merged commit SHA;
- installed script SHA-256;
- fixed root-owned script path.

The `github-runner` account receives passwordless sudo access only to:

`/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch`

The dispatcher verifies the registration, script ownership and SHA before each run. The runner must not belong to the `docker` group.

## Install after merge

After the audit pull request is squash-merged, synchronize the primary repository and install the exact merged SHA:

```bash
cd /home/andris/hermes-deals
git switch main
git pull --ff-only origin main
git status --short

AUDIT_SHA="<AUDIT_PR_SQUASH_MERGE_SHA>"
sudo bash tools/runner/install-lidl-semantic-corpus-audit-dispatcher.sh "$AUDIT_SHA"
```

The installer accepts a clean current `main` that is ahead of the registered commit. It extracts the audit script from the exact supplied commit rather than trusting the current working-tree file.

Expected final lines include:

```text
INSTALL_RESULT=PASS
AUDIT=lidl-semantic-corpus
REGISTERED_COMMIT=<sha>
SUDOERS_VALID=true
RUNNER_HAS_DOCKER_GROUP=false
PRODUCTION_APPLY_AUTHORIZED=false
```

## Trigger

Apply the label below to the merged audit pull request:

`audit:lidl-semantic-corpus`

The scheduled workflow checks that the latest action for this label was performed by the exact repository owner login and numeric GitHub ID. It then verifies that the pull request is merged into `main` and that its merge SHA remains reachable from current `main`.

A manual `workflow_dispatch` with the merged pull request number is also supported and applies the same owner and merged-SHA checks.

## Evidence

The artifact name is:

`lidl-semantic-corpus-<registered-sha>-run-<run-id>`

The sanitized artifact includes:

- overall `audit-summary.json`;
- one semantic view for each frozen corpus binding;
- coverage report, profile binding and canonical manifest;
- production-ready, Review and excluded partitions;
- exact code-input SHA-256 evidence;
- dispatcher evidence manifest;
- runner request, logs and exit codes.

The successful overall summary must show:

```json
{
  "result": "PASS",
  "corpus_binding_count": 2,
  "unexplained_count": 0,
  "deterministic_replay": true,
  "database_write": false,
  "auto_publish": false,
  "production_deploy": false,
  "production_apply_authorized": false
}
```

Issue #23 may be closed only after the real RPi5 artifact has been inspected and these conditions are verified.
