# ALDI registration refresh bridge runbook

Issue: #165. Continuation: #682 / #721.

## Purpose

This bridge closes one narrow trust-boundary gap: after the RPi5 primary Hermes Deals checkout is already aligned to one exact reviewed current-main SHA, allow `github-runner` to refresh exactly two existing root registrations without gaining generic shell, path or sudo authority:

- weekly-shadow producer registration;
- visual-card-v2 registration.

It does not fetch or read the live ALDI source, run weekly-shadow prepare, run the visual diagnostic, create or accept a request, write production data, activate a scheduler, run a canary or deploy.

## Source components

- `.github/workflows/hermes-aldi-registration-refresh.yml` — owner-gated exact-current-main workflow;
- `tools/runner/hermes-deals-aldi-registration-refresh-dispatch` — fixed root-owned runtime dispatcher after bootstrap registration;
- `tools/runner/install-aldi-registration-refresh-bridge.sh` — bootstrap-only root installer;
- `backend/tests/test_aldi_registration_refresh_bridge.py` — source trust-boundary contract.

The dispatcher may invoke only these two tracked installer paths from `/home/andris/hermes-deals`:

- `tools/runner/install-aldi-new-baseline-weekly-shadow-producer-dispatcher.sh`;
- `tools/runner/install-aldi-visual-card-bridge-v2-dispatcher.sh`.

No installer path, shell command, repository path or Git ref is supplied by the runner.

## Source-sync remains separate

The existing `Owner-gated RPi5 source checkout sync` bridge remains checkout-sync only. This ALDI bridge does not modify or chain into `.github/workflows/rpi-source-sync.yml`.

The sequence is deliberately split:

1. exact source checkout alignment under its own LIVE authorization when needed;
2. exact ALDI registration refresh under a later separate LIVE authorization;
3. only after verified registration, a later one-shot live ALDI prepare/diagnostic under another explicit owner authorization.

A successful source sync does not imply registration authority, and a successful registration refresh does not imply live ALDI source execution authority.

## Bootstrap registration

Bootstrap registration is intentionally **not self-hosting**. Source merge alone does not create a new root command or sudoers entry on RPi5.

After the bridge source is merged and the exact merged main SHA has passed repository validation, first ensure the clean primary checkout `/home/andris/hermes-deals` is on that exact SHA using an independently authorized source-sync path if required. Then obtain a **separate explicit owner LIVE authorization** for bootstrap registration only and run from the exact clean primary checkout:

```bash
sudo bash tools/runner/install-aldi-registration-refresh-bridge.sh <exact-merged-main-sha>
```

The bootstrap installer validates the exact source identity, canonical origin, clean `main`, tracked dispatcher, dispatcher syntax, `github-runner` non-Docker state and sudoers syntax before persistent writes. It installs only:

- `/usr/local/sbin/hermes-deals-aldi-registration-refresh-dispatch`;
- `/etc/hermes-deals-audits.d/aldi-registration-refresh.conf`;
- `/etc/sudoers.d/hermes-deals-aldi-registration-refresh`.

It does not invoke either ALDI registration installer. If any bootstrap error or ambiguity occurs after persistent writes begin, preserve the printed staging evidence and STOP. No retry, rollback or cleanup is implied.

## Registration refresh execution

A later ALDI registration refresh is a distinct LIVE mutation. Freshly verify the then-current GitHub `main`, exact CI and host checkout state, and obtain a separate exact-SHA owner authorization before dispatch.

Dispatch `Owner-gated ALDI registration refresh` with one input only:

`expected_main_sha=<exact current main SHA>`

The hosted authorization job requires:

- workflow execution from `main`;
- owner login `rozkalnsandris` and numeric owner ID `277435981`;
- a lowercase 40-character requested SHA;
- requested SHA equal to exact current GitHub `main`;
- successful exact-main `Hermes Deals CI checks` push run.

The self-hosted job performs no checkout and passes only the approved SHA plus its fixed runner-temp artifact directory to the registered root dispatcher.

Before the first registration mutation, the dispatcher requires:

- exact `/home/andris/hermes-deals`, `andris:andris`, non-shallow Git checkout;
- branch `main`, exact approved HEAD and fully clean worktree including untracked files;
- canonical Hermes Deals origin;
- both fixed installer paths tracked, regular, non-symlink and `bash -n` valid;
- RPi5 audit runner service active;
- `github-runner` absent from the Docker group.

Only then may it run the two fixed root installers in order. After both return success it independently re-reads both root registration files and requires both `registered_main_sha` values to equal the approved SHA, then revalidates runner active/non-Docker state.

## Sanitized evidence and fail-closed semantics

The dispatcher writes exactly one bounded `aldi-registration-refresh-summary.json` into the allowlisted runner temp directory. The workflow rejects unknown fields and rejects any receipt claiming live-source, prepare, diagnostic, request, production-data, scheduler/systemd, container, canary, deploy, rollback or cleanup side effects.

`bridge_execution_status=PASS` means both fixed registration installers completed successfully, both registration files independently bind the exact approved SHA, the runner service is active and `github-runner` is not in the Docker group.

`bridge_execution_status=BLOCKED` means the bridge failed closed. If `root_registration_mutation_started=true`, the LIVE authorization has been consumed even when only the first registration changed. Preserve the sanitized receipt and STOP. Do not retry, rollback, cleanup or switch to an alternate root path without fresh owner authorization.

## What remains after PASS

Registration PASS is not weekly-source evidence and does not advance #165 shadow acceptance by itself. A later owner decision is still required before any live ALDI source read or weekly-shadow prepare/diagnostic. Request acceptance, production DB/Review/publication writes, canary APPLY, scheduler/systemd activation and deploy remain later independent gates.

#56 remains historically incomplete; no newer baseline may be relabeled as recovery of its missing `49 current + 41 preview` evidence.

## Safety classification

- source/CI work mutates RPi5: **NO**
- bootstrap root bridge registration during source/CI: **NO**
- later authorized ALDI registration refresh: **YES, root registration only**
- live ALDI source read: **NO**
- weekly-shadow prepare/diagnostic: **NO**
- request creation/acceptance: **NO**
- production DB/Review/publication write: **NO**
- scheduler/systemd activation: **NO**
- canary: **NO**
- container mutation: **NO**
- production deploy: **NO**

**Production deploy: NO.**
