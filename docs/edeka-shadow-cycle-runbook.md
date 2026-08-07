# EDEKA Patzer weekly shadow-cycle runbook

This runbook captures one real EDEKA Patzer weekly source cycle without using the production database or changing the primary Hermes Deals worktree.

## Safety model

The EDEKA audit source is its own retailer-dedicated isolated clone:

```text
/home/andris/hermes-deals-audit-source-edeka
```

Do not reuse `/home/andris/hermes-deals-audit-source` for EDEKA. Other retailer audits may move a shared clone's branch/HEAD between runs; the dedicated path prevents that cross-retailer race.

The capture writes only to:

```text
/home/andris/hermes-deals-shadow-evidence/edeka
/home/andris/.cache/hermes-deals-edeka-shadow
```

All Git reads use `GIT_OPTIONAL_LOCKS=0`. The wrapper records and rechecks the SHA-256 and metadata of both the EDEKA audit clone index and the primary worktree index. A run fails if either index, branch, HEAD or status changes.

The capture uses the exact Patzer identity `071897` / `587881`, fetches only `https://www.edeka.de/maerkte/071897/angebote/`, creates a fresh SQLite database, persists the complete parsed batch once and requires identical replay to write zero rows.

It does not deploy, access Docker, write the production database, activate systemd timers, seed Review or publish offers.

## Prepare the isolated clone

Run as `andris` after the relevant PR is squash-merged:

```bash
AUDIT_REPO=/home/andris/hermes-deals-audit-source-edeka
REGISTERED_SHA=<SQUASH_MERGE_SHA>

if [[ ! -d "$AUDIT_REPO/.git" ]]; then
  git clone --no-hardlinks \
    https://github.com/rozkalnsandris/hermes-deals.git \
    "$AUDIT_REPO"
fi

GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" fetch origin main
git -C "$AUDIT_REPO" switch -C main "$REGISTERED_SHA"

test "$(GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" rev-parse HEAD)" = "$REGISTERED_SHA"
test "$(GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" branch --show-current)" = main
test -z "$(GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" status --porcelain)"
```

Do not switch, reset, stash or clean `/home/andris/hermes-deals`. Do not repoint another retailer's audit clone as a shortcut.

## Register the root-owned dispatcher

After the dispatcher PR is merged and the EDEKA clone is at that exact SHA, run once on RPi5:

```bash
sudo bash \
  "$AUDIT_REPO/tools/runner/install-edeka-shadow-cycle-dispatcher.sh" \
  "$REGISTERED_SHA"
```

The installer:

- reads only the EDEKA-dedicated isolated clone;
- installs the exact registered wrapper and dispatcher as `root:root`;
- creates one exact sudoers rule for the dispatcher;
- verifies the self-hosted runner is active and is not in the Docker group;
- proves the isolated Git index did not change;
- does not run the capture.

## Run from GitHub

Use the **EDEKA shadow cycle RPi5 audit** workflow and provide the merged PR number. The `workflow_dispatch` path accepts only the allowlisted repository owner and only a PR merged into `main` whose squash SHA remains reachable from current `main`.

The self-hosted job calls only:

```text
/usr/local/sbin/hermes-deals-edeka-shadow-cycle-dispatch
```

The dispatcher runs the registered wrapper as `andris`, validates the archive and Patzer bindings, rejects unsafe paths or sensitive material, and uploads a sanitized artifact retained for 30 days. It comments the result on the registered PR.

This workflow is manual only. It has no schedule, pull-request trigger or automatic production action.

## Direct owner fallback

The same registered wrapper may be run directly as `andris`:

```bash
bash "$AUDIT_REPO/tools/run-hermes-deals-edeka-shadow-cycle-v01.sh" \
  "$REGISTERED_SHA"
```

A successful run reports `RESULT=PASS`, the archive path and SHA-256, `PRIMARY_WORKTREE_MODIFIED=false`, both Git index markers as `true`, and all production/scheduler markers as `false`.

## Required two-cycle sequence

Issue #26 requires two real consecutive weekly campaigns. Capture the current campaign, then capture the next campaign after its validity start advances by exactly seven days.

Do not represent two captures of the same campaign as two cycles. The final ledger requires:

- distinct snapshot IDs, manifest SHA-256 values and raw HTML SHA-256 values;
- campaign starts exactly seven days apart;
- identical parser and normalizer versions;
- at least 150 offers in each cycle;
- every removed source-offer ID explicitly enumerated;
- no unexplained data loss;
- identical snapshot replay delta equal to zero.

After both cycle directories exist, use `app.edeka_shadow_ledger` to create the deterministic two-cycle ledger.

## Not authorized

This runbook and workflow do not authorize:

- production database writes;
- deployment or container replacement;
- systemd timer installation or activation;
- creation of `edeka-scheduler-armed`;
- Review Queue writes or decisions;
- offer publication;
- production canary apply.

Production canary preparation and apply remain separate reviewed and explicitly authorized steps.
