#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root"
[[ $# -eq 5 ]] || fail "usage: dispatcher <request-sha256> <expected-main-sha> <authorization-comment-id> <github-run-id> <artifact-dir>"

REQUEST_SHA256="$1"
EXPECTED_MAIN_SHA="$2"
AUTHORIZATION_COMMENT_ID="$3"
GITHUB_RUN_ID="$4"
EXPORT_DIR="$5"

[[ "$REQUEST_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "invalid request SHA256"
[[ "$EXPECTED_MAIN_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid expected main SHA"
[[ "$AUTHORIZATION_COMMENT_ID" =~ ^[1-9][0-9]*$ ]] || fail "invalid authorization comment id"
[[ "$GITHUB_RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail "invalid GitHub run id"

CONF='/etc/hermes-deals-audits.d/aldi-new-baseline-weekly-shadow.conf'
PRIMARY_REPO='/home/andris/hermes-deals'
[[ -f "$CONF" && ! -L "$CONF" ]] || fail "registered dispatcher config missing or unsafe"
# shellcheck disable=SC1090
source "$CONF"

for var in registered_main_sha request_root bridge_path bridge_sha256 gate_a_sha256 gate_b_sha256 gate_c_sha256 two_cycle_sha256; do
  [[ -n "${!var:-}" ]] || fail "registered config missing $var"
done

[[ "$registered_main_sha" == "$EXPECTED_MAIN_SHA" ]] || fail "registered main SHA drift"
[[ "$request_root" == '/var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01/requests' ]] || fail "request root drift"
[[ "$bridge_path" == '/usr/local/libexec/hermes-deals-audits/aldi-new-baseline-weekly-shadow-v01/aldi_new_baseline_weekly_shadow_bridge.py' ]] || fail "bridge path drift"
[[ "$(sha256sum "$bridge_path" | awk '{print $1}')" == "$bridge_sha256" ]] || fail "installed bridge hash drift"

LIBEXEC="$(dirname "$bridge_path")"
declare -A expected_hashes=(
  [aldi_new_immutable_baseline_gate.py]="$gate_a_sha256"
  [aldi_new_baseline_page_card_parity.py]="$gate_b_sha256"
  [aldi_new_baseline_gate_c_replay.py]="$gate_c_sha256"
  [aldi_new_baseline_two_cycle_shadow_gate.py]="$two_cycle_sha256"
)
for name in "${!expected_hashes[@]}"; do
  path="$LIBEXEC/$name"
  [[ -f "$path" && ! -L "$path" ]] || fail "installed gate missing or unsafe: $name"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "${expected_hashes[$name]}" ]] || fail "installed gate hash drift: $name"
done

[[ -d "$PRIMARY_REPO/.git" && ! -L "$PRIMARY_REPO/.git" ]] || fail "primary repository missing or unsafe"
git_read() {
  runuser -u andris -- env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/bin:/usr/bin:/bin \
    GIT_OPTIONAL_LOCKS=0 \
    git -C "$PRIMARY_REPO" "$@"
}
[[ "$(git_read branch --show-current)" == main ]] || fail "primary repository is not on main"
[[ -z "$(git_read status --porcelain)" ]] || fail "primary repository is dirty"
[[ "$(git_read rev-parse HEAD)" == "$EXPECTED_MAIN_SHA" ]] || fail "primary main drift"
origin="$(git_read remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "primary origin is not allowlisted" ;;
esac

REQUEST_DIR="$request_root/$REQUEST_SHA256"
[[ -d "$REQUEST_DIR" && ! -L "$REQUEST_DIR" ]] || fail "request directory missing or unsafe"
[[ "$(stat -c '%U:%G' "$REQUEST_DIR")" == 'root:root' ]] || fail "request directory must be root-owned"
mode="$(stat -c '%a' "$REQUEST_DIR")"
(( (8#$mode & 0022) == 0 )) || fail "request directory must not be group/world writable"

REQUEST_FILE="$REQUEST_DIR/request.json"
[[ -f "$REQUEST_FILE" && ! -L "$REQUEST_FILE" ]] || fail "request.json missing or unsafe"
[[ "$(stat -c '%U:%G' "$REQUEST_FILE")" == 'root:root' ]] || fail "request.json must be root-owned"
[[ "$(sha256sum "$REQUEST_FILE" | awk '{print $1}')" == "$REQUEST_SHA256" ]] || fail "request SHA256 mismatch"

tmp="$(mktemp -d /home/andris/hermes-deals-runner-evidence/aldi-new-baseline-weekly-shadow.XXXXXX)"
cleanup() { rm -rf -- "$tmp"; }
trap cleanup EXIT

install -d -o andris -g andris -m 0700 "$tmp/input"
for name in request.json gate-a-input.json gate-b-input.json gate-c-input.json execution-evidence.json prior-cycle.json observability-proofs.json; do
  src="$REQUEST_DIR/$name"
  [[ -e "$src" ]] || continue
  [[ -f "$src" && ! -L "$src" ]] || fail "unsafe request member: $name"
  [[ "$(stat -c '%U:%G' "$src")" == 'root:root' ]] || fail "request member must be root-owned: $name"
  file_mode="$(stat -c '%a' "$src")"
  (( (8#$file_mode & 0022) == 0 )) || fail "request member must not be group/world writable: $name"
  install -o andris -g andris -m 0400 "$src" "$tmp/input/$name"
done

install -d -o andris -g andris -m 0700 "$tmp/output-parent"
OUTPUT_DIR="$tmp/output-parent/evidence"

set +e
runuser -u andris -- env -i \
  HOME=/home/andris \
  PATH=/usr/local/bin:/usr/bin:/bin \
  PYTHONPATH="$LIBEXEC" \
  python3 "$bridge_path" \
    --request-dir "$tmp/input" \
    --request-sha256 "$REQUEST_SHA256" \
    --expected-main-sha "$EXPECTED_MAIN_SHA" \
    --authorization-comment-id "$AUTHORIZATION_COMMENT_ID" \
    --github-run-id "$GITHUB_RUN_ID" \
    --output-dir "$OUTPUT_DIR"
bridge_rc=$?
set -e

[[ -d "$OUTPUT_DIR" && ! -L "$OUTPUT_DIR" ]] || fail "bridge output missing"
RESULT="$OUTPUT_DIR/sanitized-result.json"
MANIFEST="$OUTPUT_DIR/MANIFEST.sha256"
[[ -f "$RESULT" && -f "$MANIFEST" && ! -L "$RESULT" && ! -L "$MANIFEST" ]] || fail "sanitized result missing"

python3 - "$OUTPUT_DIR" <<'PY'
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
allowed = {
    "MANIFEST.sha256",
    "gate-a-result.json",
    "gate-b-result.json",
    "gate-c-result.json",
    "cycle-evidence.json",
    "two-cycle-result.json",
    "sanitized-result.json",
}
members = {p.name for p in root.iterdir()}
if not members <= allowed:
    raise SystemExit(f"unexpected output members: {sorted(members - allowed)}")
if not {"MANIFEST.sha256", "sanitized-result.json"} <= members:
    raise SystemExit("required sanitized members missing")

secret_name = re.compile(r"(secret|token|password|credential|private[-_]?key|age[-_]?key)", re.I)
secret_value = re.compile(r"(gh[pousr]_[A-Za-z0-9_]{20,}|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16})")
for path in root.iterdir():
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"unsafe output member: {path.name}")
    if secret_name.search(path.name):
        raise SystemExit(f"secret-like output filename: {path.name}")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise SystemExit(f"oversized sanitized output: {path.name}")
    if path.suffix == ".json":
        text = path.read_text(encoding="utf-8")
        if secret_value.search(text):
            raise SystemExit(f"secret-like content in {path.name}")
        json.loads(text)

manifest = {}
for line in (root / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
    digest, name = line.split("  ", 1)
    if name in manifest or name == "MANIFEST.sha256":
        raise SystemExit("invalid manifest member")
    path = root / name
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"manifest path missing or unsafe: {name}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f"manifest digest mismatch: {name}")
    manifest[name] = digest

result = json.loads((root / "sanitized-result.json").read_text(encoding="utf-8"))
if result.get("decision") not in {
    "WEEKLY_SHADOW_EVIDENCE_ACCEPTED",
    "READY_FOR_PRODUCTION_CANARY_PLAN",
    "BLOCKED",
}:
    raise SystemExit("unexpected bridge decision")
for key in (
    "production_canary_authorized",
    "production_deploy_authorized",
    "production_database_write_authorized",
    "review_or_publication_write_authorized",
    "source_mutation_authorized",
    "automatic_schedule",
    "automatic_approval_or_publication",
    "historical_issue_56_completion_claimed",
):
    if result.get(key) is not False:
        raise SystemExit(f"unsafe bridge output flag: {key}")
PY

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory missing or unsafe"
[[ "$EXPORT_DIR" == "/home/github-runner/_work/_temp/aldi-new-baseline-weekly-shadow-$GITHUB_RUN_ID" ]] || fail "artifact directory outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"
[[ -z "$(find "$EXPORT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || fail "artifact directory must start empty"
while IFS= read -r -d '' src; do
  name="$(basename "$src")"
  install -o github-runner -g github-runner -m 0400 "$src" "$EXPORT_DIR/$name"
done < <(find "$OUTPUT_DIR" -maxdepth 1 -type f -print0)

printf 'DISPATCH_RESULT=%s\nREQUEST_SHA256=%s\nREGISTERED_MAIN_SHA=%s\nBRIDGE_EXIT_CODE=%s\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_PUBLICATION_WRITE=false\nSOURCE_MUTATION=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\n' \
  "$([[ "$bridge_rc" -eq 0 ]] && echo PASS || echo BLOCKED)" "$REQUEST_SHA256" "$EXPECTED_MAIN_SHA" "$bridge_rc"
exit "$bridge_rc"
