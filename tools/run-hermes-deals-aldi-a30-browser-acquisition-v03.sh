#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 027

REPO="${REPO:-/home/andris/hermes-deals}"
EXPECTED_HEAD="${HERMES_AUDIT_EXPECTED_HEAD:-}"
A21_ARCHIVE="${A21_ARCHIVE:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/hermes-deals-aldi-a21-20260801T100533Z.tar.gz}"
STATE_ROOT="${STATE_ROOT:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow}"
PYTHON_BIN="${ALDI_A30_BROWSER_PYTHON:-python3}"
BROWSER_EXECUTABLE="${ALDI_A30_BROWSER_EXECUTABLE:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${RUN_DIR:-$STATE_ROOT/a30-browser-v03-runs/$STAMP}"
LOG="$RUN_DIR/a30-browser-v03.log"

fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS %s\n' "$*"; }

for command in git tee; do
  command -v "$command" >/dev/null 2>&1 || fail "missing command: $command"
done
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python not found: $PYTHON_BIN"
[[ -n "$EXPECTED_HEAD" && "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]] \
  || fail "HERMES_AUDIT_EXPECTED_HEAD must be an exact 40-character SHA"
[[ -d "$REPO/.git" ]] || fail "repository not found: $REPO"
[[ -s "$A21_ARCHIVE" ]] || fail "pinned A2.1 archive not found: $A21_ARCHIVE"

if [[ -z "$BROWSER_EXECUTABLE" ]]; then
  for candidate in /usr/bin/chromium /usr/bin/chromium-browser /usr/bin/google-chrome; do
    if [[ -x "$candidate" ]]; then
      BROWSER_EXECUTABLE="$candidate"
      break
    fi
  done
fi
[[ -n "$BROWSER_EXECUTABLE" && -x "$BROWSER_EXECUTABLE" ]] \
  || fail "set ALDI_A30_BROWSER_EXECUTABLE to a trusted Chromium executable"
"$PYTHON_BIN" -c 'import playwright.sync_api' >/dev/null 2>&1 \
  || fail "selected Python does not contain Playwright: $PYTHON_BIN"

mkdir -p "$RUN_DIR"
exec > >(tee "$LOG") 2>&1

cd "$REPO"
[[ "$(git branch --show-current)" == "main" ]] || fail "main branch required"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" ]] || fail "HEAD mismatch"
[[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "repository must be clean"

printf 'mode=ALDI_A30_BROWSER_ACQUISITION_V03\n'
printf 'shadow_only=true\n'
printf 'frozen_a21_source_plan_only=true\n'
printf 'all_90_pages_required_for_pass=true\n'
printf 'signed_url_tokens_persisted=false\n'
printf 'production_source_write=false\n'
printf 'production_database_write=false\n'
printf 'production_deploy=false\n'
printf 'collector_execution=false\n'
printf 'automatic_approval=false\n'
printf 'automatic_publication=false\n'
printf 'browser_executable=%s\n' "$BROWSER_EXECUTABLE"

set +e
"$PYTHON_BIN" "$REPO/tools/aldi_a30_browser_acquisition.py" \
  --repo-root "$REPO" \
  --archive "$A21_ARCHIVE" \
  --output "$RUN_DIR" \
  --commit-sha "$EXPECTED_HEAD" \
  --browser-executable "$BROWSER_EXECUTABLE"
rc=$?
set -e

[[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "browser acquisition changed repository worktree"
pass "production_repository_unchanged=true"
pass "production_database_unchanged_by_construction=true"
pass "production_runtime_unchanged_by_construction=true"
printf 'RUN_DIR=%s\n' "$RUN_DIR"
printf 'SUMMARY=%s\n' "$RUN_DIR/reports/browser-acquisition-summary.json"
printf 'LOG=%s\n' "$LOG"

case "$rc" in
  0)
    printf 'RESULT=ALDI_A30_BROWSER_ACQUISITION_V03_PASS\n'
    ;;
  3)
    printf 'RESULT=ALDI_A30_BROWSER_ACQUISITION_V03_BLOCKED\n'
    ;;
  *)
    printf 'RESULT=ALDI_A30_BROWSER_ACQUISITION_V03_ERROR\n' >&2
    ;;
esac
exit "$rc"
