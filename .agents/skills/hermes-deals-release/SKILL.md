---
name: hermes-deals-release
description: Use only for guarded Hermes Deals API/UI production release preparation, plan, explicit owner-authorized apply, and post-release verification on the RPi5. Never use for database migrations, Compose, Cloudflare/DNS, destructive cleanup, B15M2 V08, or unrelated Hermes Tech work.
version: 1.0.0
metadata:
  hermes:
    tags: [hermes-deals, release, production, github]
    category: devops
---

# Hermes Deals guarded release workflow

Follow repository `AGENTS.md` and the `hermes-deals` skill first. GitHub is the source of truth for the exact `main` SHA, merged PR, source issue, CI state, release request and evidence.

## Fixed environment

- Repository: `rozkalnsandris/hermes-deals`
- Primary worktree: `/home/andris/hermes-deals`
- Detached release worktree: `/home/andris/hermes-deals-worktrees/release-control`
- Public origin: `https://deals.rozkalns.net`
- Release launcher: `tools/vscode-rpi5-release.sh`
- Runtime sync helper: `/usr/local/sbin/hermes-deals-release-runtime-sync`

Use the already authenticated `gh` CLI. Never request, print, copy, store or pass a GitHub token in a prompt, bundle, log, issue, artifact or command argument.

## Absolute safety boundaries

Always preserve all of these:

- `database_writes_authorized=false`;
- no `alembic upgrade`, `alembic downgrade` or other migration command;
- no production data mutation;
- no `docker compose up`, Compose-file change or broad container recreation outside the controlled dispatcher;
- no Cloudflare, DNS, tunnel, secret or token change;
- no `git reset`, `git clean`, stash, branch switch or edit in the primary worktree;
- no destructive deletion or manually invented rollback;
- no B15M2 issue #20 or B15M2 V08 execution;
- no alternative attempt after a guarded step returns BLOCKED, FAIL or an ambiguous result.

Stop immediately on every mismatch and report `BLOCKED` with the exact observed evidence.

## 1. Orient and identify exact main

Run from the primary worktree:

```bash
cd /home/andris/hermes-deals
git status --short
git branch --show-current
git fetch --quiet origin main
git rev-parse HEAD
git rev-parse origin/main
gh auth status
```

Require:

- current branch is `main`;
- worktree is clean;
- local `HEAD` equals `origin/main`;
- SHA is 40 lowercase hexadecimal characters;
- exact current SHA belongs to exactly one squash-merged PR targeting `main`;
- that PR closes exactly one source issue;
- source issue is not #20;
- exact-main CI is successful.

Do not fast-forward, edit or clean the primary worktree automatically. Ask the owner to synchronize it when these checks fail.

## 2. Read-only deploy check

Run:

```bash
cd /home/andris/hermes-deals
bash tools/vscode-rpi5-release.sh check
```

Accept only one of these outcomes:

- `NO DEPLOY NEEDED`: production already runs exact current main; report PASS and stop.
- `CHECK PASS`: continue.
- anything else: report BLOCKED and stop.

Record the exact production SHA, target SHA, commit count, changed-file count and schema gate from the output.

## 3. Synchronize root release runtime

Before Plan, update only the root-owned release runtime from exact current main:

```bash
sudo --non-interactive /usr/local/sbin/hermes-deals-release-runtime-sync <exact-40-sha>
```

Require all markers:

```text
RUNTIME_SYNC_RESULT=PASS
SOURCE_SHA=<exact-40-sha>
DATABASE_WRITES_AUTHORIZED=false
PRODUCTION_CHANGED=false
```

The helper may update only the detached `release-control` worktree and install the tracked dispatcher, register, bridge and auto-register components. It must not change the production API container, database, Compose, public origin or primary worktree.

On any non-zero exit or missing marker, report BLOCKED and stop. Do not bypass the helper with improvised root commands.

## 4. Controlled Plan

Run:

```bash
cd /home/andris/hermes-deals
bash tools/vscode-rpi5-release.sh plan
```

Plan must create an owner-authored `[Hermes deploy]` issue and finish with a guarded PASS. Read the issue and its comments with `gh issue view` or `gh api`.

Require:

- request exact SHA equals current `origin/main`;
- mode is `plan`;
- `owner_authorized=true`;
- `database_writes_authorized=false`;
- label/result is `hermes:deploy-pass`;
- the issue is closed after PASS;
- the release workflow succeeded;
- the expected release artifact exists, is non-empty and is bound to the exact run and SHA;
- no production change was made during Plan.

When Plan is BLOCKED or FAIL, diagnose only from the issue, workflow logs and tracked code. Never dispatch a replacement or alternative release attempt automatically.

## 5. Apply authorization gate

Never run Apply merely because the user said `deploy`, `continue`, `go`, `yes` or similar.

Require the latest owner message to contain exactly this standalone phrase for the exact planned SHA:

```text
APPLY api-ui <40-sha>
```

Before using it, re-check that:

- the phrase SHA equals exact current `origin/main`;
- the successful Plan is for the same SHA;
- no newer main commit exists;
- production is still on the same baseline observed during Check/Plan;
- no other release request is active.

If any value changed, discard the authorization and return to Check. Never construct or infer the phrase on the owner’s behalf.

## 6. Controlled Apply

Only after the exact authorization gate passes, feed the owner-provided phrase to the launcher:

```bash
cd /home/andris/hermes-deals
printf '%s\n' 'APPLY api-ui <exact-40-sha>' | bash tools/vscode-rpi5-release.sh apply
```

The controlled dispatcher is the only component allowed to recreate the production API service. It must verify image identity, API health, UI, live Alembic revision and automatic rollback invariants.

Require the Apply issue/workflow to finish with `hermes:deploy-pass`. On FAIL or rollback, report the exact result and stop. Do not patch production manually.

## 7. Independent post-release verification

After Apply PASS, run:

```bash
cd /home/andris/hermes-deals
bash tools/vscode-rpi5-release.sh check
curl -fsS --max-time 20 https://deals.rozkalns.net/api/health
curl -fsSI --max-time 20 https://deals.rozkalns.net/ui
```

Require:

- launcher reports `NO DEPLOY NEEDED` for the same exact SHA;
- public API health succeeds;
- public UI returns a successful HTTP response;
- Apply evidence reports target image revision equal to exact main;
- pre/post live Alembic revision is identical;
- `migration_commands_executed=false`;
- `database_writes_authorized=false`;
- no rollback occurred.

When public origin checks fail after workflow PASS, report FAIL with both workflow and public evidence; do not issue another Apply automatically.

## 8. Final report

Return a compact report containing:

- exact production SHA before and after;
- merged PR and source issue;
- Check result;
- runtime-sync result;
- Plan issue/run/artifact result;
- whether explicit Apply authorization was supplied;
- Apply issue/run result;
- public API/UI checks;
- unchanged Alembic result;
- rollback status;
- unresolved uncertainty;
- next smallest safe step.
