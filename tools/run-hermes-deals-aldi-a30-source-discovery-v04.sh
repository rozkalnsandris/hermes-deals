#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

RUNNER_VERSION="aldi-a30-source-discovery-v04-github"
AUDIT_REPO="${AUDIT_REPO:-/home/andris/hermes-deals-audit-source}"
PRIMARY_REPO="${PRIMARY_REPO:-/home/andris/hermes-deals}"
OLD_PREVIEW_RUN="${OLD_PREVIEW_RUN:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/a30-browser-v03-runs/20260805T114247Z}"
ENV_VERSION_DIR="${ENV_VERSION_DIR:-/home/andris/.local/share/hermes-deals/aldi-a30-playwright/playwright-1.61.0}"
ENV_FILE="${ENV_FILE:-$ENV_VERSION_DIR/a30-v03.env}"
EXPECTED_SHA="${1:-${HERMES_AUDIT_EXPECTED_HEAD:-}}"
EXPORT_ROOT="${HERMES_AUDIT_EXPORT_DIR:-}"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "expected merged commit SHA is missing or invalid"
[[ -n "$EXPORT_ROOT" ]] || fail "HERMES_AUDIT_EXPORT_DIR is required"

for command in bash git python3 readlink sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
PRIMARY_REPO="$(readlink -f -- "$PRIMARY_REPO")"
EXPORT_ROOT="$(readlink -f -- "$EXPORT_ROOT")"
[[ "$AUDIT_REPO" == "/home/andris/hermes-deals-audit-source" ]] || fail "audit repository path drift"
[[ "$PRIMARY_REPO" == "/home/andris/hermes-deals" ]] || fail "primary repository path drift"
[[ "$EXPORT_ROOT" == /home/andris/hermes-deals-runner-evidence/hermes-deals-aldi-a30-source-discovery-* ]] || fail "export root is outside audit staging allowlist"
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail "audit repository is missing or unsafe"
[[ -d "$PRIMARY_REPO/.git" && ! -L "$PRIMARY_REPO/.git" ]] || fail "primary repository is missing or unsafe"
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "isolated Playwright environment is missing or unsafe"
[[ -f "$OLD_PREVIEW_RUN/reports/browser-source-plan.json" && ! -L "$OLD_PREVIEW_RUN/reports/browser-source-plan.json" ]] || fail "old preview source plan is missing or unsafe"

read_git() { GIT_OPTIONAL_LOCKS=0 git -C "$1" "${@:2}"; }
audit_branch="$(read_git "$AUDIT_REPO" branch --show-current)"
audit_head="$(read_git "$AUDIT_REPO" rev-parse HEAD)"
audit_status="$(read_git "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)"
[[ "$audit_branch" == "main" ]] || fail "audit repository branch must be main"
[[ "$audit_head" == "$EXPECTED_SHA" ]] || fail "audit repository HEAD mismatch"
[[ -z "$audit_status" ]] || fail "audit repository is not clean"
read_git "$AUDIT_REPO" cat-file -e "$EXPECTED_SHA^{commit}" || fail "registered commit is missing"
read_git "$AUDIT_REPO" merge-base --is-ancestor "$EXPECTED_SHA" main || fail "registered commit is not reachable from audit main"
origin="$(read_git "$AUDIT_REPO" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "audit repository origin is not allowlisted" ;;
esac

AUDIT_INDEX="$AUDIT_REPO/.git/index"
PRIMARY_INDEX="$PRIMARY_REPO/.git/index"
[[ -f "$AUDIT_INDEX" && ! -L "$AUDIT_INDEX" ]] || fail "audit Git index is missing or unsafe"
[[ -f "$PRIMARY_INDEX" && ! -L "$PRIMARY_INDEX" ]] || fail "primary Git index is missing or unsafe"
audit_index_sha_before="$(sha256sum "$AUDIT_INDEX" | awk '{print $1}')"
audit_index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_INDEX")"
primary_index_sha_before="$(sha256sum "$PRIMARY_INDEX" | awk '{print $1}')"
primary_index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$PRIMARY_INDEX")"
primary_branch_before="$(read_git "$PRIMARY_REPO" branch --show-current)"
primary_head_before="$(read_git "$PRIMARY_REPO" rev-parse HEAD)"
primary_status_before="$(read_git "$PRIMARY_REPO" status --porcelain=v1 --untracked-files=all | sha256sum | awk '{print $1}')"

python3 - "$ENV_FILE" "$ENV_VERSION_DIR" <<'PY'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
root = Path(sys.argv[2]).resolve()
lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
expected = {"ALDI_A30_BROWSER_PYTHON", "ALDI_A30_BROWSER_EXECUTABLE", "PLAYWRIGHT_BROWSERS_PATH"}
values = {}
pattern = re.compile(r"^export ([A-Z0-9_]+)='([^']+)'$")
for line in lines:
    match = pattern.fullmatch(line)
    if not match:
        raise SystemExit(f"unsafe environment line: {line}")
    name, value = match.groups()
    if name in values:
        raise SystemExit(f"duplicate environment variable: {name}")
    values[name] = value
if set(values) != expected:
    raise SystemExit("Playwright environment variable contract mismatch")
for name, value in values.items():
    resolved = Path(value).resolve()
    if root != resolved and root not in resolved.parents:
        raise SystemExit(f"{name} escapes isolated environment root")
PY
# shellcheck disable=SC1090
source "$ENV_FILE"
[[ -x "$ALDI_A30_BROWSER_PYTHON" ]] || fail "isolated Python is missing"
[[ -x "$ALDI_A30_BROWSER_EXECUTABLE" ]] || fail "isolated Chromium is missing"
[[ -d "$PLAYWRIGHT_BROWSERS_PATH" && ! -L "$PLAYWRIGHT_BROWSERS_PATH" ]] || fail "isolated browser cache is missing or unsafe"
[[ "$($ALDI_A30_BROWSER_PYTHON -c 'from importlib.metadata import version; print(version("playwright"))')" == "1.61.0" ]] || fail "Playwright version mismatch"

MODULE="$AUDIT_REPO/tools/aldi_a30_source_discovery.py"
[[ -f "$MODULE" && ! -L "$MODULE" ]] || fail "source discovery module is missing or unsafe"
OUTPUT="$EXPORT_ROOT/discovery"
mkdir -m 0700 "$OUTPUT"

set +e
PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
"$ALDI_A30_BROWSER_PYTHON" "$MODULE" \
  --old-source-plan "$OLD_PREVIEW_RUN/reports/browser-source-plan.json" \
  --output "$OUTPUT" \
  --browser-executable "$ALDI_A30_BROWSER_EXECUTABLE" \
  --overview-url "https://www.aldi-nord.de/prospekte.html" \
  --commit-sha "$EXPECTED_SHA"
discovery_rc=$?
set -e
case "$discovery_rc" in
  0|3) ;;
  *) fail "source discovery runtime failed: exit=$discovery_rc" ;;
esac

REPORT="$OUTPUT/source-discovery-v04.json"
[[ -s "$REPORT" && ! -L "$REPORT" ]] || fail "source discovery report is missing or unsafe"
readarray -t markers < <(python3 - "$REPORT" "$EXPECTED_SHA" "$discovery_rc" <<'PY'
import json
from pathlib import Path
import sys
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_sha = sys.argv[2]
rc = int(sys.argv[3])
if report.get("schema_version") != 4 or report.get("mode") != "ALDI_A30_SOURCE_DISCOVERY_V04":
    raise SystemExit("unexpected report contract")
if report.get("commit_sha") != expected_sha:
    raise SystemExit("report commit binding mismatch")
if report.get("scope") != "source_discovery_only":
    raise SystemExit("report scope mismatch")
for key in ("page_acquisition_performed", "rollover_comparison_performed", "third_party_catalog_sources_used", "production_apply_authorized", "database_write_performed", "deployment_performed", "collector_executed"):
    if report.get(key) is not False:
        raise SystemExit(f"unsafe report flag: {key}")
result = report.get("result")
if rc == 0 and result != "pass":
    raise SystemExit("exit 0 without pass")
if rc == 3 and result != "blocked":
    raise SystemExit("exit 3 without controlled blocker")
print(f"RESULT={'PASS' if result == 'pass' else 'CONTROLLED_BLOCKED'}")
print(f"DISCOVERY_STATE={report.get('state')}")
print(f"CURRENT_SOURCE_VERIFIED={str(report.get('current_source_verified') is True).lower()}")
print(f"PREVIEW_SOURCE_VERIFIED={str(report.get('preview_source_verified') is True).lower()}")
print(f"SOURCE_ROOTS_DISTINCT={str(report.get('source_roots_distinct') is True).lower()}")
PY
)
printf '%s\n' "${markers[@]}"

primary_branch_after="$(read_git "$PRIMARY_REPO" branch --show-current)"
primary_head_after="$(read_git "$PRIMARY_REPO" rev-parse HEAD)"
primary_status_after="$(read_git "$PRIMARY_REPO" status --porcelain=v1 --untracked-files=all | sha256sum | awk '{print $1}')"
[[ "$primary_branch_after" == "$primary_branch_before" ]] || fail "primary branch changed"
[[ "$primary_head_after" == "$primary_head_before" ]] || fail "primary HEAD changed"
[[ "$primary_status_after" == "$primary_status_before" ]] || fail "primary status changed"
[[ "$(sha256sum "$AUDIT_INDEX" | awk '{print $1}')" == "$audit_index_sha_before" ]] || fail "audit Git index content changed"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_INDEX")" == "$audit_index_stat_before" ]] || fail "audit Git index metadata changed"
[[ "$(sha256sum "$PRIMARY_INDEX" | awk '{print $1}')" == "$primary_index_sha_before" ]] || fail "primary Git index content changed"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$PRIMARY_INDEX")" == "$primary_index_stat_before" ]] || fail "primary Git index metadata changed"

printf 'RUNNER_VERSION=%s\n' "$RUNNER_VERSION"
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'DISCOVERY_EXIT_CODE=%s\n' "$discovery_rc"
printf 'REPORT=%s\n' "$REPORT"
printf 'PRIMARY_WORKTREE_MODIFIED=false\n'
printf 'PRIMARY_GIT_INDEX_UNCHANGED=true\n'
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\n'
printf 'PAGE_ACQUISITION=false\n'
printf 'ROLLOVER_COMPARISON=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\n'
printf 'PRODUCTION_DEPLOYMENT=false\n'
printf 'COLLECTOR_EXECUTION=false\n'
exit 0
