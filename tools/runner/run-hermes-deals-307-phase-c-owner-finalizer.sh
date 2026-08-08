#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

FINALIZER_VERSION='hermes-deals-307-phase-c-owner-finalizer-v2'
REPOSITORY='rozkalnsandris/hermes-deals'
SOURCE_PR='329'
TARGET_SHA='019a33cb74cafee9d455fcf488d06f91337bc301'
PRIMARY='/home/andris/hermes-deals'
AUDIT_REPO='/home/andris/hermes-deals-audit-source-307'
INSTALLER_REL='tools/runner/install-hermes-deals-307-phase-c-dispatch.sh'
DISPATCHER='/usr/local/sbin/hermes-deals-307-phase-c-dispatch'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local rc=$?
  printf 'OWNER_FINALIZER_RESULT=FAIL\nFAILED_AT_LINE=%s\nEXIT_CODE=%s\nLOG=%s\n' \
    "${BASH_LINENO[0]:-unknown}" "$rc" "${LOG:-not-created}" >&2
  exit "$rc"
}

[[ $# -eq 0 ]] || fail 'usage: run-hermes-deals-307-phase-c-owner-finalizer.sh'
[[ "$(id -un)" == andris ]] || fail 'owner finalizer must run as andris'
for command in awk cat date gh git grep mktemp readlink sha256sum stat sudo tee; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="/home/andris/hermes-deals-307-phase-c-owner-finalizer-${stamp}.log"
INSTALL_LOG="$(mktemp /tmp/hermes-deals-307-install.XXXXXX)"
CHECK_LOG="$(mktemp /tmp/hermes-deals-307-check.XXXXXX)"
exec > >(tee -a "$LOG") 2>&1
trap on_error ERR
cleanup() {
  rm -f -- "$INSTALL_LOG" "$CHECK_LOG"
}
trap cleanup EXIT

text_sha256() {
  printf '%s' "$1" | sha256sum | awk '{print $1}'
}

file_state() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    printf 'missing\n'
    return
  fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe regular file boundary: $path"
  printf '%s:%s:%s\n' \
    "$(stat -c '%U:%G:%a:%s' "$path")" \
    "$(sha256sum "$path" | awk '{print $1}')" \
    "$(readlink -f -- "$path")"
}

git_read() {
  local repo="$1"
  shift
  local out err rc stderr_text
  out="$(mktemp /tmp/hermes-deals-307-git-out.XXXXXX)"
  err="$(mktemp /tmp/hermes-deals-307-git-err.XXXXXX)"
  set +e
  GIT_OPTIONAL_LOCKS=0 git -C "$repo" "$@" >"$out" 2>"$err"
  rc=$?
  set -e
  stderr_text="$(cat "$err")"
  if [[ "$rc" -ne 0 || -n "$stderr_text" ]]; then
    rm -f -- "$out" "$err"
    fail "read-only Git command failed closed in $repo"
  fi
  cat "$out"
  rm -f -- "$out" "$err"
}

snapshot_primary() {
  PRIMARY_BRANCH="$(git_read "$PRIMARY" branch --show-current)"
  PRIMARY_HEAD="$(git_read "$PRIMARY" rev-parse HEAD)"
  PRIMARY_STATUS="$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)"
  PRIMARY_STATUS_SHA="$(text_sha256 "$PRIMARY_STATUS")"
  PRIMARY_INDEX_PATH="$(git_read "$PRIMARY" rev-parse --path-format=absolute --git-path index)"
  [[ "$PRIMARY_INDEX_PATH" == /* ]] || fail 'primary Git index path is not absolute'
  [[ ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index lock is present'
  PRIMARY_INDEX_STATE="$(file_state "$PRIMARY_INDEX_PATH")"
}

verify_primary_unchanged() {
  local branch head status status_sha index_path index_state
  branch="$(git_read "$PRIMARY" branch --show-current)"
  head="$(git_read "$PRIMARY" rev-parse HEAD)"
  status="$(git_read "$PRIMARY" status --porcelain=v1 --untracked-files=all)"
  status_sha="$(text_sha256 "$status")"
  index_path="$(git_read "$PRIMARY" rev-parse --path-format=absolute --git-path index)"
  [[ "$index_path" == "$PRIMARY_INDEX_PATH" ]] || fail 'primary Git index path changed'
  [[ ! -e "${index_path}.lock" ]] || fail 'primary Git index lock appeared'
  index_state="$(file_state "$index_path")"
  [[ "$branch" == "$PRIMARY_BRANCH" ]] || fail 'primary branch changed'
  [[ "$head" == "$PRIMARY_HEAD" ]] || fail 'primary HEAD changed'
  [[ "$status" == "$PRIMARY_STATUS" ]] || fail 'primary worktree status changed'
  [[ "$status_sha" == "$PRIMARY_STATUS_SHA" ]] || fail 'primary status digest changed'
  [[ "$index_state" == "$PRIMARY_INDEX_STATE" ]] || fail 'primary Git index changed'
}

printf '=== Hermes Deals #307 Phase C owner finalizer ===\n'
printf 'UTC=%s\nFINALIZER_VERSION=%s\nSOURCE_PR=%s\nTARGET_SHA=%s\nLOG=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$FINALIZER_VERSION" "$SOURCE_PR" "$TARGET_SHA" "$LOG"

[[ -d "$PRIMARY/.git" && ! -L "$PRIMARY/.git" ]] || fail 'primary repository is missing or unsafe'
[[ "$(readlink -f -- "$PRIMARY")" == "$PRIMARY" ]] || fail 'primary repository path drift'
snapshot_primary
printf 'PRIMARY_BRANCH_BEFORE=%s\nPRIMARY_HEAD_BEFORE=%s\nPRIMARY_STATUS_SHA256_BEFORE=%s\n' \
  "${PRIMARY_BRANCH:-DETACHED}" "$PRIMARY_HEAD" "$PRIMARY_STATUS_SHA"

gh auth status >/dev/null
PR_META="$(gh api "repos/$REPOSITORY/pulls/$SOURCE_PR" --jq '[.merged_at // "", .merge_commit_sha // "", .base.ref // ""] | @tsv')"
IFS=$'\t' read -r PR_MERGED_AT PR_MERGE_SHA PR_BASE <<< "$PR_META"
[[ -n "$PR_MERGED_AT" ]] || fail 'source PR is not merged'
[[ "$PR_MERGE_SHA" == "$TARGET_SHA" ]] || fail 'source PR merge SHA mismatch'
[[ "$PR_BASE" == main ]] || fail 'source PR base is not main'

if [[ ! -e "$AUDIT_REPO" ]]; then
  gh repo clone "$REPOSITORY" "$AUDIT_REPO" -- --no-checkout
fi
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'dedicated #307 audit repository is missing or unsafe'
[[ "$(readlink -f -- "$AUDIT_REPO")" == "$AUDIT_REPO" ]] || fail 'dedicated #307 audit repository path drift'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'dedicated #307 audit repository ownership mismatch'
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail 'dedicated #307 audit repository has an index lock'
origin="$(git_read "$AUDIT_REPO" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'dedicated #307 audit repository origin is not allowlisted' ;;
esac

git -C "$AUDIT_REPO" fetch --prune origin main
git_read "$AUDIT_REPO" cat-file -e "$TARGET_SHA^{commit}" >/dev/null
git_read "$AUDIT_REPO" merge-base --is-ancestor "$TARGET_SHA" origin/main >/dev/null
git -C "$AUDIT_REPO" switch --detach --discard-changes "$TARGET_SHA"
[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail 'dedicated #307 audit HEAD mismatch'
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'dedicated #307 audit repository is dirty after pinned materialization'
printf 'AUDIT_REPO_MATERIALIZED=true\n'
verify_primary_unchanged

INSTALLER="$AUDIT_REPO/$INSTALLER_REL"
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] || fail 'reviewed #307 installer is missing or unsafe'
set +e
sudo bash "$INSTALLER" "$TARGET_SHA" 2>&1 | tee "$INSTALL_LOG"
INSTALL_RC=${PIPESTATUS[0]}
set -e
[[ "$INSTALL_RC" -eq 0 ]] || fail '#307 root trust installer failed'

for marker in \
  'INSTALL_RESULT=PASS' \
  "REGISTERED_COMMIT=$TARGET_SHA" \
  'SUDOERS_VALID=true' \
  'RUNNER_HAS_DOCKER_GROUP=false' \
  'ALLOWED_MODES=check,apply-dual,verify-dual' \
  'ROLLBACK_MODE_RUNNER_AUTHORIZED=false' \
  'PRODUCTION_RUNTIME_CHANGED=false' \
  'CLOUDFLARE_ROUTE_CHANGED=false' \
  'UFW_CHANGED=false' \
  'DATABASE_WRITE=false' \
  'SHARED_CLOUDFLARED_LIFECYCLE=false'; do
  grep -Fxq "$marker" "$INSTALL_LOG" || fail "installer marker mismatch: $marker"
done

[[ -f "$DISPATCHER" && ! -L "$DISPATCHER" && -x "$DISPATCHER" ]] || fail 'installed dispatcher is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$DISPATCHER")" == 'root:root:755' ]] || fail 'installed dispatcher metadata mismatch'
SUDO_LIST="$(sudo -l -U github-runner)"
printf '%s\n' "$SUDO_LIST" | grep -Fq "$DISPATCHER check" || fail 'runner check authorization is missing'
printf '%s\n' "$SUDO_LIST" | grep -Fq "$DISPATCHER apply-dual" || fail 'runner apply-dual authorization is missing'
printf '%s\n' "$SUDO_LIST" | grep -Fq "$DISPATCHER verify-dual" || fail 'runner verify-dual authorization is missing'
if printf '%s\n' "$SUDO_LIST" | grep -Fq "$DISPATCHER rollback-lan"; then
  fail 'runner rollback-lan authorization is forbidden'
fi
verify_primary_unchanged

set +e
sudo -u github-runner -- sudo --non-interactive "$DISPATCHER" check 2>&1 | tee "$CHECK_LOG"
CHECK_RC=${PIPESTATUS[0]}
set -e
[[ "$CHECK_RC" -eq 0 ]] || fail 'runner dispatcher read-only check failed'
grep -Fxq 'DISPATCH_MODE=check' "$CHECK_LOG" || fail 'dispatcher check mode marker missing'
grep -Fxq 'HERMES_DEALS_307_DUAL_BIND_CHECK=PASS' "$CHECK_LOG" || fail 'Phase C read-only check PASS marker missing'
verify_primary_unchanged

printf 'BOOTSTRAP_RESULT=PASS\n'
printf 'REGISTERED_COMMIT=%s\n' "$TARGET_SHA"
printf 'RUNNER_CHECK_AUTHORIZED=true\nRUNNER_APPLY_DUAL_AUTHORIZED=true\nRUNNER_VERIFY_DUAL_AUTHORIZED=true\n'
printf 'RUNNER_ROLLBACK_LAN_AUTHORIZED=false\n'
printf 'READ_ONLY_PHASE_C_CHECK=PASS\n'
printf 'PRIMARY_WORKTREE_UNCHANGED=true\nPRIMARY_INDEX_UNCHANGED=true\n'
printf 'PRODUCTION_RUNTIME_CHANGED=false\nCLOUDFLARE_ROUTE_CHANGED=false\nUFW_CHANGED=false\nDATABASE_WRITE=false\nSHARED_CLOUDFLARED_LIFECYCLE=false\n'
printf 'NEXT_GITHUB_ACTION=/hermes-307 apply-dual\n'
printf 'OWNER_FINALIZER_RESULT=PASS\nLOG=%s\n' "$LOG"
