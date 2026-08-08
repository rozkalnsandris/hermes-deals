#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH
export PYTHONDONTWRITEBYTECODE=1

FINALIZER_VERSION='netto-object-card-graph-audit-owner-finalizer-v1'
REPOSITORY='rozkalnsandris/hermes-deals'
SOURCE_PR='403'
TARGET_SHA='3114135cf3d41c089b7ca5de7d134e725a9e1cd8'
PRIMARY='/home/andris/hermes-deals'
WORKTREE='/home/andris/hermes-deals-worktrees/netto-object-card-graph-audit-v1'
INSTALLER_REL='tools/runner/install-netto-object-card-graph-rpi5-audit.sh'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/netto-object-card-graph-audit-v1'
DISPATCHER='/usr/local/sbin/hermes-deals-netto-object-card-graph-audit-dispatch'
CONFIG='/etc/hermes-deals-audits.d/netto-object-card-graph-audit-v1.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-netto-object-card-graph-audit'
N9_MANIFEST='/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json'
EXPECTED_N9_SHA='2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147'

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

[[ $# -eq 0 ]] || fail 'usage: run-netto-object-card-graph-audit-owner-finalizer.sh'
[[ "$(id -un)" == andris ]] || fail 'owner finalizer must run as andris'
for command in awk cat date gh git grep id install mktemp python3 readlink sha256sum stat sudo tee tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="/home/andris/netto-object-card-graph-audit-owner-finalizer-${stamp}.log"
INSTALL_LOG="$(mktemp /tmp/netto-object-card-graph-audit-install.XXXXXX)"
SUDO_LIST_LOG="$(mktemp /tmp/netto-object-card-graph-audit-sudo-list.XXXXXX)"
exec > >(tee -a "$LOG") 2>&1
trap on_error ERR
cleanup() {
  rm -f -- "$INSTALL_LOG" "$SUDO_LIST_LOG"
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
  out="$(mktemp /tmp/netto-object-card-graph-git-out.XXXXXX)"
  err="$(mktemp /tmp/netto-object-card-graph-git-err.XXXXXX)"
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

config_value() {
  local key="$1"
  awk -F= -v wanted="$key" '
    $1 == wanted {
      value=$2
      sub(/^\047/, "", value)
      sub(/\047$/, "", value)
      print value
      found=1
      exit
    }
    END { if (!found) exit 1 }
  ' "$CONFIG"
}

printf '=== Netto #305 object-card graph audit owner finalizer ===\n'
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

CI_OK="$(gh api "repos/$REPOSITORY/actions/workflows/ci.yml/runs?head_sha=$TARGET_SHA&event=push&status=completed&per_page=20" --jq '[.workflow_runs[] | select(.head_sha == "'"$TARGET_SHA"'" and .head_branch == "main" and .event == "push" and .name == "Hermes Deals CI checks" and .conclusion == "success")] | length')"
[[ "$CI_OK" -ge 1 ]] || fail 'exact source SHA has no successful main-push CI'

git -C "$PRIMARY" fetch --prune origin main
verify_primary_unchanged
git_read "$PRIMARY" cat-file -e "$TARGET_SHA^{commit}" >/dev/null
git_read "$PRIMARY" merge-base --is-ancestor "$TARGET_SHA" origin/main >/dev/null

if [[ -e "$WORKTREE" ]]; then
  [[ -d "$WORKTREE" && ! -L "$WORKTREE" ]] || fail 'object-card graph audit worktree path is unsafe'
else
  install -d -m 0755 "$(dirname "$WORKTREE")"
  git -C "$PRIMARY" worktree add --detach "$WORKTREE" "$TARGET_SHA"
fi

[[ "$(git_read "$WORKTREE" rev-parse HEAD)" == "$TARGET_SHA" ]] || fail 'object-card graph audit worktree HEAD mismatch'
[[ -z "$(git_read "$WORKTREE" branch --show-current)" ]] || fail 'object-card graph audit worktree must be detached'
[[ -z "$(git_read "$WORKTREE" status --porcelain=v1 --untracked-files=all)" ]] || fail 'object-card graph audit worktree is dirty'
[[ "$(stat -c '%U:%G' "$WORKTREE")" == andris:andris ]] || fail 'object-card graph audit worktree ownership mismatch'
COMMON_DIR="$(git_read "$WORKTREE" rev-parse --git-common-dir)"
case "$COMMON_DIR" in
  /*) COMMON_DIR="$(readlink -f -- "$COMMON_DIR")" ;;
  *) COMMON_DIR="$(readlink -f -- "$WORKTREE/$COMMON_DIR")" ;;
esac
[[ "$COMMON_DIR" == '/home/andris/hermes-deals/.git' ]] || fail 'object-card graph audit source is not a primary-repository worktree'
origin="$(git_read "$WORKTREE" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'object-card graph audit worktree origin is not allowlisted' ;;
esac
verify_primary_unchanged

INSTALLER="$WORKTREE/$INSTALLER_REL"
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] || fail 'reviewed object-card graph audit installer is missing or unsafe'
set +e
sudo bash "$INSTALLER" "$TARGET_SHA" "$WORKTREE" 2>&1 | tee "$INSTALL_LOG"
INSTALL_RC=${PIPESTATUS[0]}
set -e
[[ "$INSTALL_RC" -eq 0 ]] || fail 'object-card graph audit root trust installer failed'

for marker in \
  'INSTALL_RESULT=PASS' \
  "REGISTERED_SHA=$TARGET_SHA" \
  'AUDIT_EXECUTED=false' \
  'DATABASE_WRITE=false' \
  'REVIEW_WRITE=false' \
  'APPROVAL_PUBLICATION=false' \
  'PRODUCTION_DEPLOY=false'; do
  grep -Fxq "$marker" "$INSTALL_LOG" || fail "installer marker mismatch: $marker"
done

[[ -d "$RUNTIME_ROOT" && ! -L "$RUNTIME_ROOT" ]] || fail 'installed runtime root is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$RUNTIME_ROOT")" == 'root:root:755' ]] || fail 'installed runtime root metadata mismatch'
for member in \
  "$RUNTIME_ROOT/tools/netto_object_card_graph_audit.py" \
  "$RUNTIME_ROOT/tools/netto_card_region_topology_audit.py" \
  "$RUNTIME_ROOT/tools/netto_ownership_separator_audit.py" \
  "$RUNTIME_ROOT/tools/netto_visual_geometry_corpus_replay.py" \
  "$RUNTIME_ROOT/tools/netto_visual_geometry_shadow.py" \
  "$RUNTIME_ROOT/backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"; do
  [[ -f "$member" && ! -L "$member" ]] || fail "installed runtime member is missing or unsafe: $member"
  [[ "$(stat -c '%U:%G:%a' "$member")" == 'root:root:644' ]] || fail "installed runtime member metadata mismatch: $member"
done
[[ -f "$DISPATCHER" && ! -L "$DISPATCHER" && -x "$DISPATCHER" ]] || fail 'installed dispatcher is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$DISPATCHER")" == 'root:root:755' ]] || fail 'installed dispatcher metadata mismatch'
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail 'installed object-card graph audit config is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$CONFIG")" == 'root:root:644' ]] || fail 'installed object-card graph audit config metadata mismatch'
[[ -f "$SUDOERS" && ! -L "$SUDOERS" ]] || fail 'installed object-card graph audit sudoers is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$SUDOERS")" == 'root:root:440' ]] || fail 'installed object-card graph audit sudoers metadata mismatch'
sudo visudo -cf "$SUDOERS" >/dev/null

[[ "$(config_value audit_name)" == 'netto-object-card-graph-audit-v1' ]] || fail 'registered audit name mismatch'
[[ "$(config_value commit_sha)" == "$TARGET_SHA" ]] || fail 'registered object-card graph commit mismatch'
[[ "$(config_value runtime_root)" == "$RUNTIME_ROOT" ]] || fail 'registered runtime root mismatch'
[[ "$(config_value n9_manifest)" == "$N9_MANIFEST" ]] || fail 'registered N9 path mismatch'
[[ "$(config_value n9_manifest_sha256)" == "$EXPECTED_N9_SHA" ]] || fail 'registered N9 SHA mismatch'
[[ -f "$N9_MANIFEST" && ! -L "$N9_MANIFEST" ]] || fail 'N9 manifest is unavailable or unsafe'
[[ "$(sha256sum "$N9_MANIFEST" | awk '{print $1}')" == "$EXPECTED_N9_SHA" ]] || fail 'N9 manifest SHA256 mismatch'

PYMUPDF_VERSION="$(/usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import pymupdf
print(pymupdf.pymupdf_version)
PY
)"
[[ "$PYMUPDF_VERSION" == '1.28.0' ]] || fail "PyMuPDF 1.28.0 required, found $PYMUPDF_VERSION"

sudo -l -U github-runner > "$SUDO_LIST_LOG"
grep -Fq "$DISPATCHER" "$SUDO_LIST_LOG" || fail 'runner object-card-graph dispatcher authorization is missing'
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail 'github-runner unexpectedly belongs to Docker group'
fi
sudo -u github-runner -- sudo --non-interactive -l "$DISPATCHER" >/dev/null
verify_primary_unchanged

printf 'BOOTSTRAP_RESULT=PASS\n'
printf 'REGISTERED_COMMIT=%s\n' "$TARGET_SHA"
printf 'N9_MANIFEST_SHA256=%s\n' "$EXPECTED_N9_SHA"
printf 'PYMUPDF_VERSION=%s\nPYMUPDF_RUNTIME_USER=andris\nPYMUPDF_PYTHON=/usr/bin/python3\n' "$PYMUPDF_VERSION"
printf 'RUNNER_HAS_DOCKER_GROUP=false\n'
printf 'DISPATCHER_AUTHORIZATION_CHECK=PASS\n'
printf 'AUDIT_EXECUTED=false\n'
printf 'PRIMARY_WORKTREE_UNCHANGED=true\nPRIMARY_INDEX_UNCHANGED=true\n'
printf 'DATABASE_WRITE=false\nREVIEW_WRITE=false\nAPPROVAL_PUBLICATION=false\nPRODUCTION_DEPLOY=false\n'
printf 'NEXT_GITHUB_ACTION=apply audit:netto-object-card-graph-v1 to merged PR #403\n'
printf 'OWNER_FINALIZER_RESULT=PASS\nLOG=%s\n' "$LOG"
