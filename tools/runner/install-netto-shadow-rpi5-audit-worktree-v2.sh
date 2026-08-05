#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 2 ]] || fail "usage: sudo bash tools/runner/install-netto-shadow-rpi5-audit-worktree-v2.sh <main-commit-sha> <clean-source-worktree>"

EXPECTED_SHA="$1"
SOURCE_REPO="$(readlink -f -- "$2")"
EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-shadow-audit-install'
PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'
WORKTREE_ADMIN="$PRIMARY_GIT_COMMON_DIR/worktrees/netto-shadow-audit-install"
WORKTREE_DOT_GIT="$SOURCE_REPO/.git"
V1_INSTALLER="$SOURCE_REPO/tools/runner/install-netto-shadow-rpi5-audit-worktree.sh"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
[[ "$SOURCE_REPO" == "$EXPECTED_SOURCE_REPO" ]] || fail "source worktree must be $EXPECTED_SOURCE_REPO"

for command in cat chown find git id readlink runuser stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
id andris >/dev/null 2>&1 || fail "required local user is missing: andris"

[[ -f "$WORKTREE_DOT_GIT" && ! -L "$WORKTREE_DOT_GIT" ]] || fail "dedicated worktree .git pointer is missing or unsafe"
[[ "$(cat "$WORKTREE_DOT_GIT")" == "gitdir: $WORKTREE_ADMIN" ]] || fail "dedicated worktree .git pointer mismatch"
[[ -d "$WORKTREE_ADMIN" && ! -L "$WORKTREE_ADMIN" ]] || fail "dedicated worktree admin directory is missing or unsafe"
[[ -f "$WORKTREE_ADMIN/commondir" && ! -L "$WORKTREE_ADMIN/commondir" ]] || fail "worktree commondir metadata is missing or unsafe"
[[ -f "$WORKTREE_ADMIN/gitdir" && ! -L "$WORKTREE_ADMIN/gitdir" ]] || fail "worktree gitdir metadata is missing or unsafe"

COMMON_DIR="$(readlink -f -- "$WORKTREE_ADMIN/$(cat "$WORKTREE_ADMIN/commondir")")"
GITDIR_TARGET="$(readlink -f -- "$(cat "$WORKTREE_ADMIN/gitdir")")"
[[ "$COMMON_DIR" == "$PRIMARY_GIT_COMMON_DIR" ]] || fail "worktree common Git directory mismatch"
[[ "$GITDIR_TARGET" == "$WORKTREE_DOT_GIT" ]] || fail "worktree admin metadata does not point back to the dedicated checkout"

# The v1 installer is executed as root. Git status may otherwise refresh the
# linked-worktree index and atomically replace it with a root-owned file.
# Repair only this exact, already validated worktree admin directory, then
# suppress all optional Git index writes throughout the inherited installer.
chown -R andris:andris "$WORKTREE_ADMIN"
chown andris:andris "$WORKTREE_DOT_GIT"
export GIT_OPTIONAL_LOCKS=0

[[ -f "$V1_INSTALLER" && ! -L "$V1_INSTALLER" ]] || fail "v1 worktree installer is missing or unsafe"
/bin/bash "$V1_INSTALLER" "$EXPECTED_SHA" "$SOURCE_REPO"

UNEXPECTED_OWNER="$(find "$WORKTREE_ADMIN" -xdev \( \! -user andris -o \! -group andris \) -print -quit)"
[[ -z "$UNEXPECTED_OWNER" ]] || fail "worktree admin ownership drift remains: $UNEXPECTED_OWNER"
[[ "$(stat -c '%U:%G' "$WORKTREE_DOT_GIT")" == 'andris:andris' ]] || fail "worktree .git pointer ownership drift"

STATUS_OUTPUT=''
if ! STATUS_OUTPUT="$(runuser -u andris -- /usr/bin/env \
  GIT_OPTIONAL_LOCKS=0 \
  git -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all 2>&1)"; then
  fail "andris cannot read dedicated worktree after installation: $STATUS_OUTPUT"
fi
[[ -z "$STATUS_OUTPUT" ]] || fail "dedicated worktree is not clean after installation: $STATUS_OUTPUT"

INDEX_PATH=''
if ! INDEX_PATH="$(runuser -u andris -- /usr/bin/env \
  GIT_OPTIONAL_LOCKS=0 \
  git -C "$SOURCE_REPO" rev-parse --git-path index 2>&1)"; then
  fail "andris cannot resolve dedicated worktree index: $INDEX_PATH"
fi
INDEX_PATH="$(readlink -f -- "$INDEX_PATH")"
[[ "$INDEX_PATH" == "$WORKTREE_ADMIN/index" ]] || fail "dedicated worktree index path mismatch"
[[ "$(stat -c '%U:%G' "$INDEX_PATH")" == 'andris:andris' ]] || fail "worktree index ownership is not andris:andris"

printf 'INSTALL_RESULT=PASS\nAUDIT=netto-shadow-v1\nCOMMIT_SHA=%s\nSOURCE_REPO=%s\nWORKTREE_INDEX_OWNERSHIP=andris:andris\nGIT_OPTIONAL_LOCKS=0\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$SOURCE_REPO"
