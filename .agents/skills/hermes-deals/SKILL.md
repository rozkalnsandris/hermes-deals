---
name: hermes-deals
description: Use for Hermes Deals retailer-source investigation, Lidl/Netto store binding, leaflet/PDF/card parsing, offer persistence/provenance, API/UI deal verification, controlled production gates, and regression work. Do not use for unrelated Hermes Tech tasks.
---

# Hermes Deals workflow

Follow the repository `AGENTS.md` first.

## 1. Orient before editing

1. Run `git status --short`, `git log -5 --oneline`, and inspect the current diff.
2. Read the smallest set of source files that own the behavior.
3. Locate the newest relevant audit/log/JSON evidence available in the workspace.
4. Read `references/current-state.md` only as a dated orientation note; newer runtime evidence always wins.
5. State the verified failure in one sentence before changing code.

## 2. Retailer/browser investigations

Prefer `playwright-cli` for browser work. If the command is not on PATH, try `$HOME/.local/bin/playwright-cli`, then `npx -y @playwright/cli@latest`.

For Lidl store/region work, preserve a named session while testing state:

- inspect current URL and redirects;
- list cookies and local/session storage;
- inspect network requests and individual request details;
- compare state before and after store selection;
- record which observation proves store identity versus region/warehouse/zone identity;
- do not convert correlation into a hard-coded binding.

Put disposable browser output under `.codex/evidence/` and never save secrets/auth state into Git.

## 3. Implement minimally

- Change only the verified boundary.
- Preserve immutable SourceSnapshot/provenance behavior.
- Do not rewrite unrelated collectors/parsers.
- Add or update a focused regression test reproducing the failure when practical.
- Treat parser failures, harness failures, source changes, and production-data failures as different categories.

## 4. Verify in layers

1. Syntax/static checks relevant to touched files.
2. Focused tests for the changed behavior.
3. Replay against immutable/local evidence where available.
4. Full regression only at a phase/release/deploy gate.
5. For production: before/after counts, health, API read path, and canary evidence.

Never report success from source inspection alone when runtime verification is required.

## 5. FAST-LANE v2.1 execution

When an explicit owner FAST authorization is present:

- resolve the exact related work and keep it to one coherent risk/subsystem boundary;
- batch up to five closely related same-risk work items when that reduces duplicate PR/CI cycles without hiding review scope;
- proceed from fresh GitHub state through source changes, focused validation, branch/commit/push, Draft PR, CI and Ready without inserting artificial STOPs between those source-only steps;
- after initial publication, make at most two scope-preserving corrective commits for CI/review findings inside the original scope;
- STOP before a third corrective commit, material scope expansion, merge, runtime execution, retained write, migration, deploy or another STRICT action;
- prepare one complete Ready receipt rather than repeating the same mutable state after every micro-step.

Plain `turpini` does not grant this GitHub-write authority in Hermes Deals; it keeps the repository-local safe/read-only/source-level meaning.

## 6. Report compactly

Return:

- root cause;
- files changed;
- tests/commands and exact results;
- runtime/source evidence;
- remaining uncertainty;
- next smallest safe step.

Read `references/workflow.md` for the detailed gate checklist.
