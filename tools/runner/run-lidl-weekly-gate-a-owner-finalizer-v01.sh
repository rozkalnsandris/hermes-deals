#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

OWNER_FINALIZER_VERSION='lidl-weekly-gate-a-owner-finalizer-v01-snapshot-invariance'
PRIMARY='/home/andris/hermes-deals'
V08_SCRIPT="$PRIMARY/tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"
AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl'
INDEX="$AUDIT_REPO/.git/index"
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus/flyers'
REPOSITORY='rozkalnsandris/hermes-deals'
WORKFLOW='lidl-weekly-gate-a-rpi5.yml'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local rc=$?
  printf 'FAILED_AT_LINE=%s\nEXIT_CODE=%s\nLOG=%s\n' \
    "${BASH_LINENO[0]:-unknown}" "$rc" "${LOG:-not-created}" >&2
  exit "$rc"
}

[[ $# -eq 5 ]] || fail 'usage: finalizer <merged-sha> <merged-pr> <current|next> <YYYY-MM-DD> <true|false>'
TARGET_SHA="$1"
PR_NUMBER="$2"
TARGET="$3"
AS_OF="$4"
USE_PREVIOUS="$5"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'merged commit SHA is invalid'
[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || fail 'merged PR number is invalid'
[[ "$TARGET" == current || "$TARGET" == next ]] || fail 'target must be current or next'
[[ "$AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fail 'as-of must be YYYY-MM-DD'
[[ "$USE_PREVIOUS" == true || "$USE_PREVIOUS" == false ]] || fail 'use-previous must be true or false'
python3 - "$AS_OF" <<'PY'
from datetime import date
import sys
value = date.fromisoformat(sys.argv[1])
if value.isoformat() != sys.argv[1]:
    raise SystemExit('non-canonical as-of date')
PY

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="/home/andris/hermes-deals-lidl-gate-a-owner-finalizer-${timestamp}.log"
INSTALL_LOG="/tmp/hermes-deals-lidl-gate-a-install-${timestamp}.log"
exec > >(tee -a "$LOG") 2>&1
trap on_error ERR
cleanup() { rm -f -- "$INSTALL_LOG"; }
trap cleanup EXIT

git_read() {
  local repo="$1"
  shift
  local stdout_file stderr_file rc stderr_text
  stdout_file="$(mktemp /tmp/hermes-deals-git-read-out.XXXXXX)"
  stderr_file="$(mktemp /tmp/hermes-deals-git-read-err.XXXXXX)"
  set +e
  GIT_OPTIONAL_LOCKS=0 git -C "$repo" "$@" >"$stdout_file" 2>"$stderr_file"
  rc=$?
  set -e
  stderr_text="$(cat "$stderr_file")"
  if [[ "$rc" -ne 0 || -n "$stderr_text" ]]; then
    printf 'GIT_READ_REPOSITORY=%s\nGIT_READ_EXIT_CODE=%s\n' "$repo" "$rc" >&2
    if [[ -n "$stderr_text" ]]; then
      printf 'GIT_READ_STDERR_BEGIN\n%s\nGIT_READ_STDERR_END\n' "$stderr_text" >&2
    fi
    rm -f -- "$stdout_file" "$stderr_file"
    fail 'Git read failed closed or wrote to stderr'
  fi
  cat "$stdout_file"
  rm -f -- "$stdout_file" "$stderr_file"
}

text_sha256() {
  printf '%s' "$1" | sha256sum | awk '{print $1}'
}

file_state() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    printf 'missing\n'
    return
  fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe protected file: $path"
  printf '%s:%s:%s\n' \
    "$(stat -c '%U:%G:%a:%s' "$path")" \
    "$(sha256sum "$path" | awk '{print $1}')" \
    "$(readlink -f -- "$path")"
}

verify_primary_unchanged() {
  local branch_now head_now status_now status_sha_now index_path_now index_now v08_now
  branch_now="$(git_read "$PRIMARY" branch --show-current)"
  head_now="$(git_read "$PRIMARY" rev-parse HEAD)"
  status_now="$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)"
  status_sha_now="$(text_sha256 "$status_now")"
  index_path_now="$(git_read "$PRIMARY" rev-parse --path-format=absolute --git-path index)"
  [[ "$index_path_now" == "$PRIMARY_INDEX_PATH_BEFORE" ]] || fail 'primary Git index path changed'
  [[ ! -e "${index_path_now}.lock" ]] || fail 'primary Git index lock appeared'
  index_now="$(file_state "$index_path_now")"
  v08_now="$(file_state "$V08_SCRIPT")"
  [[ "$branch_now" == "$PRIMARY_BRANCH_BEFORE" ]] || fail 'primary branch changed'
  [[ "$head_now" == "$PRIMARY_HEAD_BEFORE" ]] || fail 'primary HEAD changed'
  [[ "$status_now" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary worktree status changed'
  [[ "$status_sha_now" == "$PRIMARY_STATUS_SHA256_BEFORE" ]] || fail 'primary status digest changed'
  [[ "$index_now" == "$PRIMARY_INDEX_BEFORE" ]] || fail 'primary Git index changed'
  [[ "$v08_now" == "$PRIMARY_V08_BEFORE" ]] || fail 'protected B15M2 V08 file changed'
}

verify_audit_registered_state() {
  [[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail 'audit repository HEAD changed'
  [[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit repository changed'
  [[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership changed'
  [[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail 'audit Git index lock appeared'
  [[ "$(file_state "$INDEX")" == "$AUDIT_INDEX_REGISTERED" ]] || fail 'audit Git index content changed'
}

printf '=== Lidl weekly Gate A owner finalizer ===\n'
printf 'UTC=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'OWNER_FINALIZER_VERSION=%s\n' "$OWNER_FINALIZER_VERSION"
printf 'TARGET_SHA=%s\nPR_NUMBER=%s\nTARGET=%s\nAS_OF=%s\nUSE_PREVIOUS=%s\nLOG=%s\n' \
  "$TARGET_SHA" "$PR_NUMBER" "$TARGET" "$AS_OF" "$USE_PREVIOUS" "$LOG"

[[ "$(id -un)" == andris ]] || fail 'owner finalizer must run as andris'
for command in awk cat date gh git grep head mktemp python3 readlink sed sha256sum stat sudo tee; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
[[ "$(readlink -f -- "$PRIMARY")" == "$PRIMARY" ]] || fail 'primary repository path drift'
[[ "$(readlink -f -- "$AUDIT_REPO")" == "$AUDIT_REPO" ]] || fail 'audit repository path drift'
[[ -e "$PRIMARY/.git" ]] || fail 'primary repository is missing'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'audit repository is missing or unsafe'
[[ -f "$INDEX" && ! -L "$INDEX" ]] || fail 'audit Git index is missing or unsafe'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository ownership mismatch'
[[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership mismatch'
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail 'audit repository has a stale index lock'
[[ "$(readlink -f -- "$CORPUS_ROOT")" == "$CORPUS_ROOT" ]] || fail 'authoritative corpus root path drift'
[[ -d "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT" ]] || fail 'authoritative corpus root is missing or unsafe'
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == andris:andris ]] || fail 'authoritative corpus root ownership mismatch'

PRIMARY_BRANCH_BEFORE="$(git_read "$PRIMARY" branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read "$PRIMARY" rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)"
PRIMARY_STATUS_SHA256_BEFORE="$(text_sha256 "$PRIMARY_STATUS_BEFORE")"
PRIMARY_INDEX_PATH_BEFORE="$(git_read "$PRIMARY" rev-parse --path-format=absolute --git-path index)"
[[ "$PRIMARY_INDEX_PATH_BEFORE" == /* ]] || fail 'primary Git index path is not absolute'
[[ -f "$PRIMARY_INDEX_PATH_BEFORE" && ! -L "$PRIMARY_INDEX_PATH_BEFORE" ]] || fail 'primary Git index is missing or unsafe'
[[ ! -e "${PRIMARY_INDEX_PATH_BEFORE}.lock" ]] || fail 'primary repository has a stale index lock'
PRIMARY_INDEX_BEFORE="$(file_state "$PRIMARY_INDEX_PATH_BEFORE")"
PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"
printf 'PRIMARY_BRANCH_BEFORE=%s\nPRIMARY_HEAD_BEFORE=%s\nPRIMARY_STATUS_SHA256_BEFORE=%s\nPRIMARY_INDEX_PATH_BEFORE=%s\nPRIMARY_INDEX_STATE_BEFORE=%s\nPRIMARY_V08_STATE_BEFORE=%s\nPRIMARY_GIT_STDERR_POLICY=empty-required\n' \
  "${PRIMARY_BRANCH_BEFORE:-DETACHED}" "$PRIMARY_HEAD_BEFORE" "$PRIMARY_STATUS_SHA256_BEFORE" \
  "$PRIMARY_INDEX_PATH_BEFORE" "$PRIMARY_INDEX_BEFORE" "$PRIMARY_V08_BEFORE"
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit repository is not clean'

origin="$(git_read "$AUDIT_REPO" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "audit repository origin is not allowlisted: $origin" ;;
esac

git -C "$AUDIT_REPO" fetch --prune origin main
git_read "$AUDIT_REPO" cat-file -e "$TARGET_SHA^{commit}"
git_read "$AUDIT_REPO" merge-base --is-ancestor "$TARGET_SHA" origin/main
git -C "$AUDIT_REPO" switch -C main "$TARGET_SHA"
[[ "$(git_read "$AUDIT_REPO" branch --show-current)" == main ]] || fail 'audit repository branch is not main'
[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail 'audit repository HEAD mismatch'
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit repository became dirty'
[[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership drift'
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail 'audit Git index lock appeared'
AUDIT_INDEX_REGISTERED="$(file_state "$INDEX")"
printf 'AUDIT_INDEX_STATE_REGISTERED=%s\n' "$AUDIT_INDEX_REGISTERED"

INSTALLER="$AUDIT_REPO/tools/runner/install-lidl-weekly-gate-a-dispatcher.sh"
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] || fail 'Gate A installer is missing or unsafe'
set +e
sudo bash "$INSTALLER" "$TARGET_SHA" 2>&1 | tee "$INSTALL_LOG"
INSTALL_RC=${PIPESTATUS[0]}
set -e
[[ "$INSTALL_RC" -eq 0 ]] || fail 'Gate A installer failed'
for marker in \
  'INSTALL_RESULT=PASS' \
  'AUDIT=lidl-weekly-gate-a' \
  "REGISTERED_COMMIT=$TARGET_SHA" \
  'AUDIT_GIT_INDEX_UNCHANGED=true' \
  'SUDOERS_VALID=true' \
  'RUNNER_HAS_DOCKER_GROUP=false' \
  'PRODUCTION_DATABASE_WRITE=false' \
  'REVIEW_WRITE=false' \
  'PRODUCTION_PUBLISH=false' \
  'PRODUCTION_DEPLOY=false' \
  'SYSTEMD_CHANGE=false'; do
  grep -Fxq "$marker" "$INSTALL_LOG" || fail "installer marker mismatch: $marker"
done
IMAGE_ID="$(sed -n 's/^REGISTERED_IMAGE_ID=//p' "$INSTALL_LOG" | tail -n 1)"
[[ "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'installer registered image ID is invalid'
printf 'REGISTERED_IMAGE_ID=%s\n' "$IMAGE_ID"
verify_audit_registered_state
verify_primary_unchanged
printf 'PRIMARY_WORKTREE_VERIFIED_UNCHANGED=true\nPRIMARY_INDEX_VERIFIED_UNCHANGED=true\nPRIMARY_V08_VERIFIED_UNCHANGED=true\nAUDIT_CLONE_HEAD=%s\n' "$TARGET_SHA"

gh auth status
DISPATCH_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUN_OUTPUT="$(gh workflow run "$WORKFLOW" --repo "$REPOSITORY" --ref main \
  -f "pr_number=$PR_NUMBER" \
  -f "target=$TARGET" \
  -f "as_of=$AS_OF" \
  -f "use_previous=$USE_PREVIOUS")"
printf '%s\n' "$RUN_OUTPUT"
RUN_ID="$(printf '%s\n' "$RUN_OUTPUT" | sed -nE 's#.*actions/runs/([0-9]+).*#\1#p' | tail -n 1)"
if [[ ! "$RUN_ID" =~ ^[0-9]+$ ]]; then
  sleep 4
  RUN_ID="$(gh run list --repo "$REPOSITORY" --workflow "$WORKFLOW" --event workflow_dispatch --limit 10 \
    --json databaseId,createdAt \
    --jq ".[] | select(.createdAt >= \"$DISPATCH_STARTED\") | .databaseId" | head -n 1)"
fi
[[ "$RUN_ID" =~ ^[0-9]+$ ]] || fail 'could not determine Gate A workflow run ID'
printf 'WORKFLOW_RUN_ID=%s\nWORKFLOW_RUN_URL=https://github.com/%s/actions/runs/%s\n' "$RUN_ID" "$REPOSITORY" "$RUN_ID"
gh run watch "$RUN_ID" --repo "$REPOSITORY" --exit-status

verify_primary_unchanged
verify_audit_registered_state
printf 'WORKFLOW_RESULT=PASS\n'
printf 'PRIMARY_WORKTREE_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true\nPRIMARY_INDEX_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true\nPRIMARY_V08_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true\n'
printf 'OWNER_FINALIZER_RESULT=PASS\nLOG=%s\n' "$LOG"