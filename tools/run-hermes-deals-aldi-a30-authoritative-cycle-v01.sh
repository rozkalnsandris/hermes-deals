#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

[[ $# -eq 1 ]] || { echo "usage: $0 <registered-sha>" >&2; exit 2; }
EXPECTED_SHA="$1"
AUDIT_REPO="/home/andris/hermes-deals-audit-source"
PRIMARY_REPO="/home/andris/hermes-deals"
PLAN="$AUDIT_REPO/config/aldi-a30-authoritative-cycle-2026cw32-cw33.json"
ENV_FILE="/home/andris/.local/share/hermes-deals/aldi-a30-playwright/playwright-1.61.0/a30-v03.env"
OUT_ROOT="/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/a30-authoritative-cycle-github"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_ROOT/$STAMP"
EVIDENCE_DIR="$OUT/evidence"
PREFLIGHT_DIR="$OUT/preflight"

fail() {
  printf 'FAIL %s\n' "$*" >&2
  printf 'PRIMARY_WORKTREE_VERIFICATION=failed\n'
  printf 'PRIMARY_WORKTREE_MODIFIED=unknown\n'
  printf 'PRODUCTION_DATABASE_WRITE=false\n'
  printf 'PRODUCTION_DEPLOYMENT=false\n'
  printf 'B15M2_V08_ACTION=false\n'
  printf 'EVIDENCE_DIR=%s\n' "$EVIDENCE_DIR"
  exit 1
}

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid SHA"
for command in git readlink sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || fail "missing command: $command"
done
mkdir -p "$PREFLIGHT_DIR"

capture_repo_snapshot() {
  local repo="$1"
  local label="$2"
  local prefix="$PREFLIGHT_DIR/$label"
  local stderr_file="$prefix.git-stderr.txt"
  local status_file="$prefix.status-porcelain-v1-z.bin"
  local branch_file="$prefix.branch.txt"
  local head_file="$prefix.head.txt"
  local git_dir_file="$prefix.git-dir.txt"
  local git_dir branch head status_sha index_sha index_stat

  [[ -d "$repo" && ! -L "$repo" ]] || {
    printf '%s repository is missing or unsafe\n' "$label" > "$stderr_file"
    return 1
  }

  : > "$stderr_file"
  if ! GIT_OPTIONAL_LOCKS=0 git -C "$repo" rev-parse --absolute-git-dir \
      > "$git_dir_file" 2> "$stderr_file"; then
    return 1
  fi
  [[ ! -s "$stderr_file" ]] || return 1
  git_dir="$(readlink -f -- "$(cat "$git_dir_file")")"
  [[ -d "$git_dir" ]] || {
    printf '%s git directory is missing\n' "$label" > "$stderr_file"
    return 1
  }
  [[ -f "$git_dir/index" && ! -L "$git_dir/index" && -r "$git_dir/index" ]] || {
    printf '%s git index is missing, unsafe, or unreadable\n' "$label" > "$stderr_file"
    return 1
  }
  [[ ! -e "$git_dir/index.lock" ]] || {
    printf '%s git index lock exists\n' "$label" > "$stderr_file"
    return 1
  }

  : > "$stderr_file"
  if ! GIT_OPTIONAL_LOCKS=0 git -C "$repo" branch --show-current \
      > "$branch_file" 2> "$stderr_file"; then
    return 1
  fi
  [[ ! -s "$stderr_file" ]] || return 1
  branch="$(cat "$branch_file")"

  : > "$stderr_file"
  if ! GIT_OPTIONAL_LOCKS=0 git -C "$repo" rev-parse HEAD \
      > "$head_file" 2> "$stderr_file"; then
    return 1
  fi
  [[ ! -s "$stderr_file" ]] || return 1
  head="$(cat "$head_file")"
  [[ "$head" =~ ^[0-9a-f]{40}$ ]] || {
    printf '%s HEAD is invalid\n' "$label" > "$stderr_file"
    return 1
  }

  : > "$stderr_file"
  : > "$status_file"
  if ! GIT_OPTIONAL_LOCKS=0 git -C "$repo" status \
      --porcelain=v1 -z --untracked-files=all \
      > "$status_file" 2> "$stderr_file"; then
    return 1
  fi
  # A Git implementation can leave a misleadingly hashable empty stdout
  # stream after an index error. Any stderr therefore blocks the audit.
  [[ ! -s "$stderr_file" ]] || return 1

  status_sha="$(sha256sum "$status_file" | awk '{print $1}')"
  index_sha="$(sha256sum "$git_dir/index" | awk '{print $1}')"
  index_stat="$(stat -c '%U:%G:%a:%s:%Y:%i' "$git_dir/index")"
  printf '%s\n' \
    "repo=$repo" \
    "git_dir=$git_dir" \
    "branch=$branch" \
    "head=$head" \
    "status_sha256=$status_sha" \
    "index_sha256=$index_sha" \
    "index_stat=$index_stat" \
    > "$prefix.snapshot.txt"
  printf '%s|%s|%s|%s|%s\n' \
    "$branch" "$head" "$status_sha" "$index_sha" "$index_stat"
}

audit_before="$(capture_repo_snapshot "$AUDIT_REPO" audit)" \
  || fail "audit repository snapshot failed; see $PREFLIGHT_DIR/audit.git-stderr.txt"
primary_before="$(capture_repo_snapshot "$PRIMARY_REPO" primary)" \
  || fail "primary repository snapshot failed; see $PREFLIGHT_DIR/primary.git-stderr.txt"

IFS='|' read -r audit_branch audit_head audit_status_sha _audit_index_sha _audit_index_stat \
  <<< "$audit_before"
[[ "$audit_branch" == "main" ]] || fail "audit repository branch mismatch"
[[ "$audit_head" == "$EXPECTED_SHA" ]] || fail "audit repository HEAD mismatch"
empty_status_sha="$(printf '' | sha256sum | awk '{print $1}')"
[[ "$audit_status_sha" == "$empty_status_sha" ]] || fail "audit repository is dirty"

[[ -f "$PLAN" && ! -L "$PLAN" ]] || fail "frozen acquisition plan missing or unsafe"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "Playwright environment missing or unsafe"
[[ -f "$AUDIT_REPO/tools/aldi_a30_rollover_review.py" ]] \
  || fail "rollover review analyzer missing"
source "$ENV_FILE"

set +e
PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  "$ALDI_A30_BROWSER_PYTHON" \
  "$AUDIT_REPO/tools/aldi_a30_authoritative_cycle.py" \
  --plan "$PLAN" \
  --output "$EVIDENCE_DIR" \
  --browser-executable "$ALDI_A30_BROWSER_EXECUTABLE" \
  --commit-sha "$EXPECTED_SHA"
acquisition_rc=$?
set -e

analysis_rc=0
if [[ -d "$EVIDENCE_DIR" ]]; then
  mkdir -p "$EVIDENCE_DIR/preflight"
  cp -a "$PREFLIGHT_DIR/." "$EVIDENCE_DIR/preflight/"
fi
if [[ "$acquisition_rc" -eq 0 || "$acquisition_rc" -eq 3 ]]; then
  [[ -f "$EVIDENCE_DIR/authoritative-cycle-report.json" ]] \
    || fail "authoritative-cycle report missing after controlled acquisition"
  set +e
  PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
    "$ALDI_A30_BROWSER_PYTHON" \
    "$AUDIT_REPO/tools/aldi_a30_rollover_review.py" \
    --plan "$PLAN" \
    --evidence "$EVIDENCE_DIR" \
    --browser-executable "$ALDI_A30_BROWSER_EXECUTABLE"
  analysis_rc=$?
  set -e
fi

audit_after="$(capture_repo_snapshot "$AUDIT_REPO" audit-after)" \
  || fail "audit repository post-run snapshot failed"
primary_after="$(capture_repo_snapshot "$PRIMARY_REPO" primary-after)" \
  || fail "primary repository post-run snapshot failed"
[[ "$audit_after" == "$audit_before" ]] || fail "audit repository changed during run"
[[ "$primary_after" == "$primary_before" ]] || fail "primary repository changed during run"

rc="$acquisition_rc"
if [[ "$analysis_rc" -ne 0 ]]; then
  rc=1
fi
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'AUDIT_REPOSITORY_VERIFICATION=pass\n'
printf 'PRIMARY_WORKTREE_VERIFICATION=pass\n'
printf 'PRIMARY_WORKTREE_MODIFIED=false\n'
printf 'ROLLOVER_REVIEW_ANALYSIS_EXIT_CODE=%s\n' "$analysis_rc"
printf 'PRODUCTION_DATABASE_WRITE=false\n'
printf 'PRODUCTION_DEPLOYMENT=false\n'
printf 'B15M2_V08_ACTION=false\n'
printf 'EVIDENCE_DIR=%s\n' "$EVIDENCE_DIR"
printf 'AUDIT_EXIT_CODE=%s\n' "$rc"
exit "$rc"
