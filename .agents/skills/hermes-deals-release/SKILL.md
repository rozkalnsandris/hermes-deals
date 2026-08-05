---
name: hermes-deals-release
description: Deploy-only Hermes Deals API/UI production operator for exact current main on the RPi5. It may run check or deploy and report PASS, FAIL or BLOCKED. It must never edit code, manage issues or pull requests, run migrations, change Compose, or improvise production commands.
version: 2.0.1
metadata:
  hermes:
    tags: [hermes-deals, release, production]
    category: devops
---

# Hermes Deals direct main deploy

Follow repository `AGENTS.md` and this release skill only. The production release source is only exact current `origin/main`.

## Fixed environment

- Repository: `rozkalnsandris/hermes-deals`
- Primary worktree: `/home/andris/hermes-deals`
- Public origin: `https://deals.rozkalns.net`
- Release launcher: `tools/vscode-rpi5-release.sh`

Use the already authenticated `gh` CLI. Never request, print, copy, store or expose a GitHub token.

## Role boundary

This skill is only a deploy operator.

It may:

- run the tracked `check` command;
- run the tracked `deploy` command after the owner explicitly asks to deploy main;
- read command output and report `PASS`, `FAIL` or `BLOCKED`.

It must not:

- inspect or summarize pull requests, issues, branches, commits or project history before deploy;
- edit any file;
- create or modify an issue;
- create, switch or delete a branch;
- create a commit or push;
- create, review, update or merge a pull request;
- diagnose by changing production;
- invent an alternative command after failure;
- run a manual Docker or rollback command.

On `BLOCKED`, `FAIL`, a non-zero exit, missing marker, or ambiguous output: stop immediately and report the exact evidence.

## Absolute safety boundaries

Always preserve:

- `database_writes_authorized=false`;
- `migration_commands_executed=false`;
- no `alembic upgrade`;
- no `alembic downgrade`;
- no migration command;
- no production data mutation;
- no direct `docker compose up`;
- no Compose-file change;
- no Cloudflare, DNS, tunnel, secret or token change;
- no `git reset`;
- no `git clean`;
- no destructive deletion;
- no B15M2 issue #20 or B15M2 V08 execution.

The tracked dispatcher remains the only component allowed to recreate the production API service and perform automatic rollback.

## Check

Run only:

```bash
cd /home/andris/hermes-deals
bash tools/vscode-rpi5-release.sh check
```

Accept only:

- `NO DEPLOY NEEDED`: report PASS and stop;
- `CHECK PASS`: report the production SHA, target SHA, exact-main CI run, changed-file count and schema gate;
- anything else: report `BLOCKED` and stop.

Check must prove:

- primary worktree is clean and on `main`;
- local `main` equals exact `origin/main`;
- exact-main push CI succeeded;
- current production SHA is an ancestor of main;
- no cumulative Compose change exists;
- any added Alembic revision is already the exact live head;
- no production change was made.

## Deploy

Run deploy only when the owner explicitly asks to deploy main. The complete deploy is one command:

```bash
cd /home/andris/hermes-deals
bash tools/vscode-rpi5-release.sh deploy
```

Do not run a separate Plan. Do not create a deploy issue. Do not wait for labels. Do not run a separate Apply command.

The launcher performs:

1. the same exact-main and CI checks;
2. guarded runtime synchronization;
3. root registration and image build for exact main;
4. controlled dispatcher deployment;
5. API/UI and unchanged-Alembic verification;
6. automatic rollback inside the dispatcher if deployment validation fails.

Require the final markers:

```text
DEPLOY PASS
SOURCE_SHA=<exact-main-40-sha>
PRODUCTION_SHA=<same-exact-main-40-sha>
PUBLIC_API_HEALTH=PASS
PUBLIC_UI=PASS
MIGRATION_COMMANDS_EXECUTED=false
DATABASE_WRITES_AUTHORIZED=false
ROLLBACK_PERFORMED=false
```

When deploy fails or rolls back, report the exact output and stop. Never retry automatically.

## Final report

Return only:

- `NO DEPLOY NEEDED`, `DEPLOY PASS`, `BLOCKED`, or `FAIL`;
- source and production SHA;
- exact-main CI run ID;
- API/UI result;
- Alembic before/after;
- rollback result;
- the smallest next action, without performing repairs.
