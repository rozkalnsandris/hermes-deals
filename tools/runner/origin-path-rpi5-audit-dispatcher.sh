#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 3 ]] || fail "usage: hermes-deals-origin-path-audit-dispatch <registered-sha> <as-of> <artifact-dir>"

EXPECTED_SHA="$1"
AS_OF="$2"
EXPORT_DIR="$3"
CONF='/etc/hermes-deals-audits.d/origin-path-audit.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
python3 - "$AS_OF" <<'PY'
import datetime
import sys

value = sys.argv[1]
try:
    parsed = datetime.date.fromisoformat(value)
except ValueError as error:
    raise SystemExit("invalid as_of date") from error
if parsed.isoformat() != value:
    raise SystemExit("as_of must use canonical YYYY-MM-DD format")
PY

[[ -f "$CONF" && ! -L "$CONF" ]] || fail "origin path audit registration is missing"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "registration ownership is invalid"
[[ "$(stat -c '%a' "$CONF")" == '600' ]] || fail "registration permissions are invalid"
# shellcheck disable=SC1090
source "$CONF"

[[ "${audit_name:-}" == 'origin-path-audit' ]] || fail "registration name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested SHA is not registered"
[[ "${probe_path:-}" == '/usr/local/libexec/hermes-deals-audits/origin-path-probe.py' ]] || fail "registered probe path is invalid"
[[ "${probe_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered probe SHA is invalid"
[[ "${dispatcher_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered dispatcher SHA is invalid"
[[ "${workflow_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered workflow SHA is invalid"
[[ "${public_base_url:-}" == 'https://deals.rozkalns.net' ]] || fail "public base URL registration mismatch"
[[ "${origin_base_url:-}" == 'http://192.168.0.180:9128' ]] || fail "origin base URL registration mismatch"
[[ "${origin_host:-}" == 'deals.rozkalns.net' ]] || fail "origin host registration mismatch"
[[ "${timeout_seconds:-}" == '5' ]] || fail "timeout registration mismatch"

[[ -f "$probe_path" && ! -L "$probe_path" ]] || fail "registered probe is missing or unsafe"
[[ "$(stat -c '%U:%G' "$probe_path")" == 'root:root' ]] || fail "probe ownership is invalid"
[[ "$(sha256sum "$probe_path" | awk '{print $1}')" == "$probe_sha256" ]] || fail "probe content drift"
self_path="$(readlink -f -- "$0")"
[[ "$self_path" == '/usr/local/sbin/hermes-deals-origin-path-audit-dispatch' ]] || fail "dispatcher path is invalid"
[[ "$(stat -c '%U:%G' "$self_path")" == 'root:root' ]] || fail "dispatcher ownership is invalid"
[[ "$(sha256sum "$self_path" | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail "dispatcher content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-origin-path-audit-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

run_key="$(basename -- "$EXPORT_DIR")"
[[ "$run_key" =~ ^hermes-deals-origin-path-audit-[0-9]+-[0-9]+$ ]] || fail "unexpected artifact directory name"
staging="$STAGING_ROOT/$run_key"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
[[ ! -e "$staging" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$staging"
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT

set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris SHELL=/bin/bash \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 \
  /usr/bin/python3 "$probe_path" \
    --public-base-url "$public_base_url" \
    --origin-base-url "$origin_base_url" \
    --origin-host "$origin_host" \
    --as-of "$AS_OF" \
    --timeout "$timeout_seconds" \
    --output "$staging/probe-report.json" \
  > "$staging/probe-stdout.json" \
  2> "$staging/probe-stderr.txt"
probe_rc=$?
set -e

destination="$EXPORT_DIR/audit-evidence"
python3 - "$staging" "$destination" "$EXPECTED_SHA" "$AS_OF" "$probe_rc" <<'PY'
import hashlib
import json
import os
import pathlib
import sys
from urllib.parse import urlsplit

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
commit_sha = sys.argv[3]
as_of = sys.argv[4]
probe_rc = int(sys.argv[5])

manifest = {
    "schema_version": 1,
    "audit": "origin-path-audit",
    "commit_sha": commit_sha,
    "as_of": as_of,
    "probe_exit_code": probe_rc,
    "sanitization_passed": False,
    "production_apply_authorized": False,
    "production_database_write": False,
    "production_deployment": False,
    "restart_or_configuration_mutation": False,
}
destination.mkdir(mode=0o700, parents=False, exist_ok=False)

report_path = source / "probe-report.json"
if not report_path.is_file() or report_path.is_symlink():
    manifest["error"] = "probe_report_missing"
else:
    if report_path.stat().st_size > 1024 * 1024:
        raise SystemExit("probe report exceeds 1 MiB")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if set(report) != {
        "schema_version",
        "captured_at",
        "as_of",
        "classification",
        "severity",
        "probes",
    }:
        raise SystemExit("unexpected probe report fields")
    if report["schema_version"] != "1" or report["as_of"] != as_of:
        raise SystemExit("probe report identity mismatch")

    allowed_classifications = {
        "healthy": ("ok", 0),
        "edge_or_tunnel_failure": ("failed", 2),
        "public_path_failure": ("degraded", 1),
        "origin_or_application_failure": ("failed", 2),
        "local_origin_probe_failure": ("degraded", 1),
        "mixed_failure": ("degraded", 1),
    }
    classification = report["classification"]
    if classification not in allowed_classifications:
        raise SystemExit("unexpected classification")
    expected_severity, expected_rc = allowed_classifications[classification]
    if report["severity"] != expected_severity or probe_rc != expected_rc:
        raise SystemExit("classification, severity and exit code disagree")

    probes = report["probes"]
    if not isinstance(probes, list) or len(probes) != 6:
        raise SystemExit("expected exactly six probes")
    allowed_probe_fields = {
        "target",
        "endpoint",
        "url",
        "ok",
        "status",
        "elapsed_ms",
        "transport_error",
        "headers",
        "problem",
    }
    allowed_headers = {
        "cf-ray",
        "retry-after",
        "server",
        "content-type",
        "cf-cache-status",
    }
    allowed_problem = {
        "status",
        "error_code",
        "error_name",
        "ray_id",
        "retryable",
        "retry_after",
    }
    expected_pairs = {
        ("public", "health"),
        ("origin", "health"),
        ("public", "overview"),
        ("origin", "overview"),
        ("public", "deals"),
        ("origin", "deals"),
    }
    captured_at = report["captured_at"]
    if not isinstance(captured_at, str) or len(captured_at) > 64:
        raise SystemExit("captured_at is invalid")
    seen = set()
    for item in probes:
        if not isinstance(item, dict) or set(item) != allowed_probe_fields:
            raise SystemExit("unexpected probe fields")
        if type(item["ok"]) is not bool:
            raise SystemExit("probe ok flag is invalid")
        if item["status"] is not None and (
            type(item["status"]) is not int
            or not 100 <= item["status"] <= 599
        ):
            raise SystemExit("probe status is invalid")
        if type(item["elapsed_ms"]) is not int or not 0 <= item["elapsed_ms"] <= 60000:
            raise SystemExit("probe elapsed time is invalid")
        pair = (item["target"], item["endpoint"])
        seen.add(pair)
        raw_url = item["url"]
        if not isinstance(raw_url, str) or len(raw_url) > 2048:
            raise SystemExit("probe URL is invalid")
        parsed = urlsplit(raw_url)
        if item["target"] == "public":
            if parsed.scheme != "https" or parsed.netloc != "deals.rozkalns.net":
                raise SystemExit("public probe URL escaped allowlist")
        elif item["target"] == "origin":
            if parsed.scheme != "http" or parsed.netloc != "192.168.0.180:9128":
                raise SystemExit("origin probe URL escaped allowlist")
        else:
            raise SystemExit("unexpected probe target")
        if parsed.username is not None or parsed.password is not None:
            raise SystemExit("probe URL contains credentials")
        if not isinstance(item["headers"], dict) or not set(item["headers"]).issubset(allowed_headers):
            raise SystemExit("unsafe response header entered report")
        for value in item["headers"].values():
            if not isinstance(value, str) or len(value) > 512 or "\r" in value or "\n" in value:
                raise SystemExit("unsafe response header value entered report")
        if not isinstance(item["problem"], dict) or not set(item["problem"]).issubset(allowed_problem):
            raise SystemExit("unsafe problem field entered report")
        for value in item["problem"].values():
            if isinstance(value, str) and (
                len(value) > 256 or "\r" in value or "\n" in value
            ):
                raise SystemExit("unsafe problem value entered report")
            if not isinstance(value, (str, int, float, bool)):
                raise SystemExit("unexpected problem value type")
        if item["transport_error"] not in {
            None,
            "timeout",
            "connection_error",
            "transport_error",
        }:
            raise SystemExit("unexpected transport error")
    if seen != expected_pairs:
        raise SystemExit("probe target/endpoint coverage mismatch")

    canonical = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target = destination / "probe-report.json"
    target.write_text(canonical, encoding="utf-8")
    os.chmod(target, 0o600)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    manifest.update(
        {
            "classification": classification,
            "severity": report["severity"],
            "probe_report_sha256": digest,
            "sanitization_passed": True,
        }
    )

manifest_path = destination / "dispatcher-manifest.json"
manifest_path.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.chmod(manifest_path, 0o600)
exit_path = destination / "audit-exit-code.txt"
exit_path.write_text(f"{probe_rc}\n", encoding="utf-8")
os.chmod(exit_path, 0o600)
PY

chown -R github-runner:github-runner "$destination"
find "$destination" -type d -exec chmod 0700 {} +
find "$destination" -type f -exec chmod 0600 {} +
printf 'AUDIT=origin-path-audit\nREGISTERED_COMMIT=%s\nAS_OF=%s\nPROBE_EXIT_CODE=%s\n' \
  "$EXPECTED_SHA" "$AS_OF" "$probe_rc"
printf 'PRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\nRESTART_OR_CONFIGURATION_MUTATION=false\n'
exit "$probe_rc"
