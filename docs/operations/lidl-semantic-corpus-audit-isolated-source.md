# Lidl semantic corpus audit from an isolated source clone

This runbook keeps `/home/andris/hermes-deals` untouched when it is reserved for another controlled branch such as B15M2 V08 preparation.

## Trust boundary

The audit source is a separate full Git clone at:

```text
/home/andris/hermes-deals-audit-source
```

The clone must be:

- owned by `andris:andris`;
- on branch `main`;
- clean;
- at the exact squash-merge SHA being registered;
- connected to `rozkalnsandris/hermes-deals` through an allowlisted origin URL.

The V02 installer invokes the original V01 installer in a private mount namespace. Only that installer process sees the isolated clone at the legacy `/home/andris/hermes-deals` path. The real primary worktree is not switched, reset, stashed, cleaned or modified.

## Create the isolated clone

Run as `andris` after the V02 pull request is squash-merged:

```bash
PRIMARY=/home/andris/hermes-deals
AUDIT_REPO=/home/andris/hermes-deals-audit-source
AUDIT_SHA=<V02_SQUASH_MERGE_SHA>

[[ ! -e "$AUDIT_REPO" ]]
git -C "$PRIMARY" fetch origin main
git clone --no-hardlinks "$PRIMARY" "$AUDIT_REPO"
git -C "$AUDIT_REPO" remote set-url origin https://github.com/rozkalnsandris/hermes-deals.git
git -C "$AUDIT_REPO" fetch origin main
git -C "$AUDIT_REPO" switch -C main "$AUDIT_SHA"

test "$(git -C "$AUDIT_REPO" rev-parse HEAD)" = "$AUDIT_SHA"
test "$(git -C "$AUDIT_REPO" branch --show-current)" = main
test -z "$(git -C "$AUDIT_REPO" status --porcelain)"
```

The primary repository branch and status must remain unchanged before and after these commands.

## Install the registered audit

```bash
sudo bash "$AUDIT_REPO/tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v02.sh" \
  "$AUDIT_SHA"
```

Required final evidence includes:

```text
INSTALL_RESULT=PASS
AUDIT_VERSION=lidl-semantic-corpus-audit-v02-isolated-source
REGISTERED_COMMIT=<V02_SQUASH_MERGE_SHA>
ISOLATED_SOURCE_REPO=/home/andris/hermes-deals-audit-source
PRIMARY_WORKTREE_MODIFIED=false
SUDOERS_VALID=true
RUNNER_HAS_DOCKER_GROUP=false
PRODUCTION_APPLY_AUTHORIZED=false
```

## Trigger and inspect

Apply `audit:lidl-semantic-corpus` to the merged V02 pull request. The scheduled workflow authorizes only an owner-applied label, the exact merged PR SHA and current `main` ancestry.

The artifact must prove both frozen corpus bindings were processed, every row belongs to exactly one semantic partition, `unexplained_count` is zero, and deterministic replay passed.

## Safety boundaries

This path does not authorize:

- production deployment;
- database writes or migrations;
- Review seeding;
- approval or publication;
- Docker access;
- B15M2 V08 execution.
