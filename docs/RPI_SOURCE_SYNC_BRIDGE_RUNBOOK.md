# RPi5 source-sync bridge runbook

Issue: #759. Refs #758, #749, #741.

## Purpose

This bridge provides one narrowly scoped live capability: fast-forward the primary Hermes Deals source checkout at `/home/andris/hermes-deals` to one exact reviewed merge SHA selected by an owner-gated GitHub workflow.

It exists to separate **source checkout synchronization** from production deploy, DB mutation, root registration of other bridges, retained-evidence operations, diagnostics, scheduler/systemd actions and runtime activation.

Source merge does not activate this capability. Source work and CI do not mutate the RPi5.

## Trust boundary

The bridge has two source components:

- `tools/runner/hermes-deals-rpi-source-sync-dispatch` — fixed root-owned dispatcher after registration;
- `tools/runner/install-rpi-source-sync-bridge.sh` — root registration installer.

The GitHub workflow is `.github/workflows/rpi-source-sync.yml`.

The workflow accepts only `target_pr_number`. The hosted authorizer resolves the exact squash merge SHA from a same-repository PR merged to `main`, requires owner login `rozkalnsandris` and numeric owner ID `277435981`, proves the merge SHA is reachable from current `main`, and requires successful exact CI or exact tree-equivalent PR-head CI. The self-hosted job receives only that approved SHA.

The self-hosted job has `permissions: {}`, performs no repository checkout and can invoke only:

`sudo --non-interactive /usr/local/sbin/hermes-deals-rpi-source-sync-dispatch <approved-sha> <runner-temp-artifact-dir>`

## Bootstrap registration

The first bootstrap registration is intentionally **not self-hosting**. Before the root dispatcher/sudoers rule exists, the workflow cannot install itself and must not attempt to bypass that privilege boundary.

After #759 is merged and its exact merge SHA is freshly verified, the merged source containing the installer must first be present on the RPi5 through an independently owner-controlled host path. That initial source arrival is a host mutation and requires its own explicit owner authorization.

Then obtain a separate explicit owner authorization for **bootstrap registration only** and run on the RPi5 from the exact clean primary checkout:

```bash
sudo bash tools/runner/install-rpi-source-sync-bridge.sh <exact-merged-main-sha>
```

The installer requires:

- exact `/home/andris/hermes-deals`, owned by `andris:andris` and not a symlink;
- branch `main`, non-shallow checkout, exact authorized HEAD, fully clean including untracked files;
- canonical Hermes Deals origin;
- `github-runner` not in the Docker group;
- tracked non-symlink dispatcher source with valid shell syntax;
- valid sudoers syntax before persistent writes.

Registration installs only the root-owned dispatcher, config and one least-privilege sudoers rule. It does **not** run Git fetch, does **not** move the checkout and does **not** invoke any diagnostic/deploy/runtime action.

If installer failure or ambiguity occurs after persistent registration writes begin, preserve the printed evidence/staging path and **STOP**. No retry, rollback, cleanup or alternate installation path is authorized without a new owner decision.

## Later source-sync execution

A later source checkout synchronization is a distinct host mutation. Freshly verify GitHub state first and obtain explicit owner authorization bound to the intended merged PR/target SHA.

Manually dispatch `Owner-gated RPi5 source checkout sync` with the exact merged PR number. Do not pass a shell command, path or arbitrary ref; the workflow resolves the target SHA itself.

The dispatcher then:

1. validates the root registration and dispatcher self-hash;
2. validates the runner-temp receipt directory;
3. validates exact checkout path/owner/non-shallow `main`/clean state/canonical origin;
4. performs one fixed public Git fetch of only `refs/heads/main` into `refs/remotes/origin/main`;
5. requires local HEAD -> target and target -> freshly fetched remote main ancestry;
6. if needed, executes only a hook-disabled `git merge --ff-only <target-sha>`;
7. validates exact target HEAD, clean state, branch and origin after sync;
8. emits only `rpi-source-sync-summary.json` into the runner artifact directory.

There is no reset, checkout, switch, pull, clean, force update, rollback or automatic retry path.

## PASS / BLOCKED semantics

`bridge_execution_status=PASS` means the dispatcher completed all checks and the primary checkout ends at the exact authorized target SHA. It does not mean any production/runtime bridge is registered or executed.

`bridge_execution_status=BLOCKED` means a fail-closed condition occurred. If the fixed Git fetch had already started, the source-sync live authorization is consumed even if checkout HEAD did not change. Preserve the sanitized receipt and **STOP**. No retry or alternate mutation path without fresh authorization.

A missing/invalid sanitized receipt also makes the workflow fail closed.

## Relationship to Kaufland #758

A successful source sync only aligns `/home/andris/hermes-deals`. It does **not** register or run the Kaufland K3C diagnostic bridge merged in #758.

After a successful source sync to a source revision containing #758, the Kaufland sequence remains separate:

1. explicit owner authorization for root Kaufland K3C bridge registration;
2. registration verification and STOP on error/ambiguity;
3. later, separately authorized read-only Kaufland K3C diagnostic execution;
4. review sanitized structural evidence before any public-promo semantic acceptance or #702 parser implementation.

Source-sync authorization never implies any of these later gates.

## Safety classification

- RPi source checkout mutation during source/CI work: **NO**
- root source-sync bridge registration during source/CI work: **NO**
- later authorized source-sync host mutation: **YES, only exact checkout fast-forward**
- production deploy: **NO**
- production DB write: **NO**
- Review/publication write: **NO**
- retained evidence read/write: **NO**
- Kaufland K3C diagnostic execution: **NO**
- scraper/runtime activation: **NO**
- scheduler/systemd change: **NO**
- Cloudflare mutation: **NO**
- container mutation: **NO**
- package installation: **NO**

**Production deploy: NO.**
