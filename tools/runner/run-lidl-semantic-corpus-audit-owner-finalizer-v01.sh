#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

OWNER_FINALIZER_VERSION="lidl-semantic-corpus-owner-finalizer-v01"
EXPECTED_AUDIT_VERSION="lidl-semantic-corpus-audit-v02.3-partition-contract"
EXPECTED_DISPATCHER_VERSION="lidl-semantic-corpus-dispatcher-v03-owned-log"

PRIMARY="/home/andris/hermes-deals"
PRIMARY_EXPECTED_BRANCH="audit/b15m2-v08-preparation"
PRIMARY_EXPECTED_HEAD="a2d9e20039275832286b229984b8261f9394554f"
V08_SCRIPT="$PRIMARY/tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"

AUDIT_REPO="/home/andris/hermes-deals-audit-source"
INDEX="$AUDIT_REPO/.git/index"
CORPUS_ROOT="/home/andris/hermes-deals-lidl-corpus/flyers"

REPOSITORY="rozkalnsandris/hermes-deals"
WORKFLOW="lidl-semantic-corpus-rpi5-audit.yml"

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

[[ $# -eq 2 ]] ||
  fail "usage: $0 <merged-commit-sha> <merged-pr-number>"

TARGET_SHA="$1"
PR_NUMBER="$2"
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] ||
  fail "merged commit SHA is invalid"
[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] ||
  fail "merged PR number is invalid"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="/home/andris/hermes-deals-lidl-semantic-owner-finalizer-${timestamp}.log"
INSTALL_LOG="/tmp/hermes-deals-lidl-semantic-owner-finalizer-install-${timestamp}.log"

exec > >(tee -a "$LOG") 2>&1
trap on_error ERR

cleanup() {
  rm -f -- "$INSTALL_LOG"
}
trap cleanup EXIT

git_read() {
  GIT_OPTIONAL_LOCKS=0 git -C "$1" "${@:2}"
}

file_state() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    printf 'missing\n'
    return
  fi
  [[ -f "$path" && ! -L "$path" ]] ||
    fail "unsafe protected file: $path"
  printf '%s:%s:%s\n' \
    "$(stat -c '%U:%G:%a:%s' "$path")" \
    "$(sha256sum "$path" | awk '{print $1}')" \
    "$(readlink -f -- "$path")"
}

verify_primary_unchanged() {
  local branch_now head_now status_now v08_now

  branch_now="$(git_read "$PRIMARY" branch --show-current)"
  head_now="$(git_read "$PRIMARY" rev-parse HEAD)"
  status_now="$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)"
  v08_now="$(file_state "$V08_SCRIPT")"

  [[ "$branch_now" == "$PRIMARY_BRANCH_BEFORE" ]] ||
    fail "primary branch changed"
  [[ "$head_now" == "$PRIMARY_HEAD_BEFORE" ]] ||
    fail "primary HEAD changed"
  [[ "$status_now" == "$PRIMARY_STATUS_BEFORE" ]] ||
    fail "primary worktree status changed"
  [[ "$v08_now" == "$PRIMARY_V08_BEFORE" ]] ||
    fail "protected B15M2 V08 file changed"
}

printf '=== Lidl semantic corpus owner finalizer ===\n'
printf 'UTC=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'OWNER_FINALIZER_VERSION=%s\n' "$OWNER_FINALIZER_VERSION"
printf 'TARGET_SHA=%s\n' "$TARGET_SHA"
printf 'PR_NUMBER=%s\n' "$PR_NUMBER"
printf 'LOG=%s\n' "$LOG"

[[ "$(id -un)" == "andris" ]] ||
  fail "owner finalizer must run as andris"

for command in date gh git grep head readlink sed sha256sum stat sudo tee; do
  command -v "$command" >/dev/null 2>&1 ||
    fail "required command is missing: $command"
done

[[ "$(readlink -f -- "$PRIMARY")" == "$PRIMARY" ]] ||
  fail "primary repository path drift"
[[ "$(readlink -f -- "$AUDIT_REPO")" == "$AUDIT_REPO" ]] ||
  fail "audit repository path drift"
[[ -e "$PRIMARY/.git" ]] ||
  fail "primary repository is missing"
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] ||
  fail "audit repository is missing or unsafe"
[[ -f "$INDEX" && ! -L "$INDEX" ]] ||
  fail "audit Git index is missing or unsafe"
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == "andris:andris" ]] ||
  fail "audit repository ownership is invalid"
[[ "$(stat -c '%U:%G' "$INDEX")" == "andris:andris" ]] ||
  fail "audit Git index ownership is invalid"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] ||
  fail "audit repository has a stale index lock"

[[ "$(readlink -f -- "$CORPUS_ROOT")" == "$CORPUS_ROOT" ]] ||
  fail "authoritative corpus root path drift"
[[ -d "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT" ]] ||
  fail "authoritative corpus root is missing or unsafe"
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == "andris:andris" ]] ||
  fail "authoritative corpus root ownership is invalid"

PRIMARY_BRANCH_BEFORE="$(git_read "$PRIMARY" branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read "$PRIMARY" rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(
  git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all
)"
PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"

printf 'PRIMARY_BRANCH_BEFORE=%s\n' "$PRIMARY_BRANCH_BEFORE"
printf 'PRIMARY_HEAD_BEFORE=%s\n' "$PRIMARY_HEAD_BEFORE"
printf 'PRIMARY_V08_STATE_BEFORE=%s\n' "$PRIMARY_V08_BEFORE"

[[ "$PRIMARY_BRANCH_BEFORE" == "$PRIMARY_EXPECTED_BRANCH" ]] ||
  fail "protected primary branch differs from expected baseline"
[[ "$PRIMARY_HEAD_BEFORE" == "$PRIMARY_EXPECTED_HEAD" ]] ||
  fail "protected primary HEAD differs from expected baseline"

[[ -z "$(
  git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all
)" ]] || fail "audit repository is not clean"

origin="$(git_read "$AUDIT_REPO" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|\
  https://github.com/rozkalnsandris/hermes-deals.git|\
  git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "audit repository origin is not allowlisted: $origin" ;;
esac

git -C "$AUDIT_REPO" fetch --prune origin main
git_read "$AUDIT_REPO" cat-file -e "$TARGET_SHA^{commit}"
git_read "$AUDIT_REPO" merge-base --is-ancestor "$TARGET_SHA" origin/main
git -C "$AUDIT_REPO" switch -C main "$TARGET_SHA"

[[ "$(git_read "$AUDIT_REPO" branch --show-current)" == "main" ]] ||
  fail "audit repository branch is not main"
[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] ||
  fail "audit repository HEAD mismatch"
[[ -z "$(
  git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all
)" ]] || fail "audit repository became dirty"
[[ "$(stat -c '%U:%G' "$INDEX")" == "andris:andris" ]] ||
  fail "audit Git index ownership drift"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] ||
  fail "audit Git index lock appeared"

INSTALLER="$AUDIT_REPO/tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v03.sh"
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] ||
  fail "dispatcher V03 installer is missing or unsafe"

set +e
sudo bash "$INSTALLER" "$TARGET_SHA" 2>&1 | tee "$INSTALL_LOG"
install_rc=${PIPESTATUS[0]}
set -e
[[ "$install_rc" -eq 0 ]] ||
  fail "dispatcher V03 installer failed"

grep -Fxq "INSTALL_RESULT=PASS" "$INSTALL_LOG" ||
  fail "installer did not report PASS"
grep -Fxq "AUDIT_VERSION=$EXPECTED_AUDIT_VERSION" "$INSTALL_LOG" ||
  fail "installer audit version mismatch"
grep -Fxq "DISPATCHER_VERSION=$EXPECTED_DISPATCHER_VERSION" "$INSTALL_LOG" ||
  fail "installer dispatcher version mismatch"
grep -Fxq "REGISTERED_COMMIT=$TARGET_SHA" "$INSTALL_LOG" ||
  fail "installer registered commit mismatch"
grep -Fxq "PRIMARY_WORKTREE_MODIFIED=false" "$INSTALL_LOG" ||
  fail "installer primary-worktree safety flag mismatch"
grep -Fxq "AUDIT_GIT_INDEX_UNCHANGED=true" "$INSTALL_LOG" ||
  fail "installer Git-index safety flag mismatch"
grep -Fxq "RUNNER_HAS_DOCKER_GROUP=false" "$INSTALL_LOG" ||
  fail "runner Docker-group safety flag mismatch"
grep -Fxq "PRODUCTION_APPLY_AUTHORIZED=false" "$INSTALL_LOG" ||
  fail "production apply safety flag mismatch"

[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] ||
  fail "audit repository HEAD changed during install"
[[ -z "$(
  git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all
)" ]] || fail "audit repository changed during install"
[[ "$(stat -c '%U:%G' "$INDEX")" == "andris:andris" ]] ||
  fail "audit Git index ownership changed during install"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] ||
  fail "installer left an index lock"

verify_primary_unchanged
printf 'PRIMARY_WORKTREE_VERIFIED_UNCHANGED=true\n'
printf 'PRIMARY_V08_VERIFIED_UNCHANGED=true\n'
printf 'AUDIT_CLONE_HEAD=%s\n' "$TARGET_SHA"

gh auth status

dispatch_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
run_output="$(
  gh workflow run "$WORKFLOW" \
    --repo "$REPOSITORY" \
    --ref main \
    -f "pr_number=$PR_NUMBER"
)"
printf '%s\n' "$run_output"

run_id="$(
  printf '%s\n' "$run_output" |
    sed -nE 's#.*actions/runs/([0-9]+).*#\1#p' |
    tail -n 1
)"

if [[ ! "$run_id" =~ ^[0-9]+$ ]]; then
  sleep 4
  run_id="$(
    gh run list \
      --repo "$REPOSITORY" \
      --workflow "$WORKFLOW" \
      --event workflow_dispatch \
      --limit 10 \
      --json databaseId,createdAt \
      --jq ".[] | select(.createdAt >= \"$dispatch_started\") | .databaseId" |
      head -n 1
  )"
fi

[[ "$run_id" =~ ^[0-9]+$ ]] ||
  fail "could not determine workflow run ID"

printf 'WORKFLOW_RUN_ID=%s\n' "$run_id"
printf 'WORKFLOW_RUN_URL=https://github.com/%s/actions/runs/%s\n' \
  "$REPOSITORY" "$run_id"

gh run watch "$run_id" \
  --repo "$REPOSITORY" \
  --exit-status

verify_primary_unchanged
[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] ||
  fail "audit repository HEAD changed during workflow"
[[ -z "$(
  git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all
)" ]] || fail "audit repository changed during workflow"
[[ "$(stat -c '%U:%G' "$INDEX")" == "andris:andris" ]] ||
  fail "audit Git index ownership changed during workflow"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] ||
  fail "workflow left an audit Git index lock"

printf 'WORKFLOW_RESULT=PASS\n'
printf 'PRIMARY_WORKTREE_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true\n'
printf 'PRIMARY_V08_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true\n'
printf 'OWNER_FINALIZER_RESULT=PASS\n'
printf 'LOG=%s\n' "$LOG"
