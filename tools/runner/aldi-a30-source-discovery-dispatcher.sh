#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-aldi-a30-source-discovery-dispatch <registered-sha> <artifact-dir>"

EXPECTED_SHA="$1"
EXPORT_DIR="$2"
CONF='/etc/hermes-deals-audits.d/aldi-a30-source-discovery.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ -f "$CONF" && ! -L "$CONF" ]] || fail "ALDI source-discovery registration is missing"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "registration ownership is invalid"
[[ "$(stat -c '%a' "$CONF")" =~ ^(600|640|644)$ ]] || fail "registration permissions are invalid"
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == 'aldi-a30-source-discovery' ]] || fail "registration name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested SHA is not registered"
[[ "${script_path:-}" == '/usr/local/libexec/hermes-deals-audits/aldi-a30-source-discovery.sh' ]] || fail "registered script path is invalid"
[[ "${script_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered script SHA is invalid"
[[ -f "$script_path" && ! -L "$script_path" ]] || fail "registered script is missing or unsafe"
[[ "$(stat -c '%U:%G' "$script_path")" == 'root:root' ]] || fail "registered script ownership is invalid"
[[ "$(sha256sum "$script_path" | awk '{print $1}')" == "$script_sha256" ]] || fail "registered script content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-aldi-a30-source-discovery-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

run_key="$(basename -- "$EXPORT_DIR")"
[[ "$run_key" =~ ^hermes-deals-aldi-a30-source-discovery-[0-9]+-[0-9]+$ ]] || fail "unexpected artifact directory name"
staging="$STAGING_ROOT/$run_key"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
[[ ! -e "$staging" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$staging"
install -o andris -g andris -m 0600 /dev/null "$staging/audit-execution.log"
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT

set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris SHELL=/bin/bash \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 HERMES_AUDIT_TRIGGER=github-actions \
  HERMES_AUDIT_EXPECTED_HEAD="$EXPECTED_SHA" \
  HERMES_AUDIT_EXPORT_DIR="$staging" \
  /bin/bash --noprofile --norc "$script_path" "$EXPECTED_SHA" \
  > "$staging/audit-execution.log" 2>&1
audit_rc=$?
set -e

python3 - "$staging" "$EXPORT_DIR/audit-evidence" "$EXPECTED_SHA" "$audit_rc" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
commit_sha = sys.argv[3]
audit_rc = int(sys.argv[4])
log = source / "audit-execution.log"
if not log.is_file() or log.is_symlink():
    raise SystemExit("audit execution log is missing or unsafe")
text = log.read_text(encoding="utf-8", errors="replace")

def marker(name: str) -> str:
    values = re.findall(rf"(?m)^{re.escape(name)}=(.+)$", text)
    if len(values) != 1:
        raise SystemExit(f"expected exactly one {name} marker")
    return values[0].strip()

manifest = {
    "schema_version": 1,
    "audit": "aldi-a30-source-discovery",
    "audit_exit_code": audit_rc,
    "commit_sha": commit_sha,
    "sanitization_passed": False,
    "production_apply_authorized": False,
}
if audit_rc == 0:
    required = {
        "REGISTERED_COMMIT": commit_sha,
        "PRIMARY_WORKTREE_MODIFIED": "false",
        "PRIMARY_GIT_INDEX_UNCHANGED": "true",
        "AUDIT_GIT_INDEX_UNCHANGED": "true",
        "PAGE_ACQUISITION": "false",
        "ROLLOVER_COMPARISON": "false",
        "PRODUCTION_DATABASE_WRITE": "false",
        "PRODUCTION_DEPLOYMENT": "false",
        "COLLECTOR_EXECUTION": "false",
    }
    for key, expected in required.items():
        if marker(key) != expected:
            raise SystemExit(f"unexpected {key} marker")
    result = marker("RESULT")
    if result not in {"PASS", "CONTROLLED_BLOCKED"}:
        raise SystemExit("unexpected source-discovery result marker")
    discovery_exit = marker("DISCOVERY_EXIT_CODE")
    if discovery_exit not in {"0", "3"}:
        raise SystemExit("unexpected discovery exit marker")
    if (result, discovery_exit) not in {("PASS", "0"), ("CONTROLLED_BLOCKED", "3")}:
        raise SystemExit("result and discovery exit markers disagree")

sensitive_name = re.compile(r"(?:^|/)(?:\.env(?:\..*)?|[^/]+\.(?:pgpass|pem|key)|production\.dump)$", re.I)
sensitive_content = re.compile(
    rb"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}|PGPASSWORD=|postgresql(?:\+[^:]+)?://[^\s:/]+:[^\s@]+@)",
    re.I,
)
files = []
total = 0
for path in sorted(source.rglob("*")):
    relative = path.relative_to(source)
    pure = PurePosixPath(relative.as_posix())
    info = path.lstat()
    if pure.is_absolute() or ".." in pure.parts:
        raise SystemExit(f"unsafe evidence path: {relative}")
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise SystemExit(f"unsafe evidence member type: {relative}")
    if sensitive_name.search(relative.as_posix()):
        raise SystemExit(f"sensitive evidence filename: {relative}")
    if stat.S_ISREG(info.st_mode):
        total += info.st_size
        if total > 100 * 1024 * 1024:
            raise SystemExit("evidence exceeds 100 MiB")
        if info.st_size <= 8 * 1024 * 1024 and sensitive_content.search(path.read_bytes()):
            raise SystemExit(f"sensitive evidence content: {relative}")
        files.append((path, relative, info.st_size))
if not files:
    raise SystemExit("audit produced no evidence")

report = source / "discovery" / "source-discovery-v04.json"
if audit_rc == 0:
    if not report.is_file() or report.is_symlink():
        raise SystemExit("source discovery report is missing or unsafe")
    payload = json.loads(report.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 4 or payload.get("mode") != "ALDI_A30_SOURCE_DISCOVERY_V04":
        raise SystemExit("unexpected source discovery report contract")
    if payload.get("commit_sha") != commit_sha:
        raise SystemExit("source discovery report commit mismatch")
    for key in (
        "page_acquisition_performed",
        "rollover_comparison_performed",
        "third_party_catalog_sources_used",
        "production_apply_authorized",
        "database_write_performed",
        "deployment_performed",
        "collector_executed",
    ):
        if payload.get(key) is not False:
            raise SystemExit(f"unsafe report flag: {key}")
    manifest["discovery"] = {
        "result": payload.get("result"),
        "state": payload.get("state"),
        "current_source_verified": payload.get("current_source_verified"),
        "preview_source_verified": payload.get("preview_source_verified"),
        "source_roots_distinct": payload.get("source_roots_distinct"),
    }

destination.mkdir(mode=0o700, parents=False, exist_ok=False)
file_manifest = []
for path, relative, size in files:
    target = destination / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(path, target, follow_symlinks=False)
    os.chmod(target, 0o600)
    file_manifest.append({"path": relative.as_posix(), "bytes": size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
manifest["files"] = file_manifest
manifest["total_bytes"] = total
manifest["sanitization_passed"] = True
manifest_path = destination / "dispatcher-evidence-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(manifest_path, 0o600)
PY

printf '%s\n' "$audit_rc" > "$EXPORT_DIR/audit-evidence/audit-exit-code.txt"
chown -R github-runner:github-runner "$EXPORT_DIR/audit-evidence"
find "$EXPORT_DIR/audit-evidence" -type d -exec chmod 0700 {} +
find "$EXPORT_DIR/audit-evidence" -type f -exec chmod 0600 {} +
printf 'AUDIT=aldi-a30-source-discovery\nREGISTERED_COMMIT=%s\nAUDIT_EXIT_CODE=%s\nPRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\n' "$EXPECTED_SHA" "$audit_rc"
exit "$audit_rc"
