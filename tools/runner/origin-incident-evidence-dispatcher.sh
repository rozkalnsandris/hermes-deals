#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 4 ]] || fail "usage: hermes-deals-origin-incident-evidence-dispatch <registered-sha> <incident-at> <window-minutes> <artifact-dir>"

EXPECTED_SHA="$1"
INCIDENT_AT="$2"
WINDOW_MINUTES="$3"
EXPORT_DIR="$4"
CONF='/etc/hermes-deals-audits.d/origin-incident-evidence.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
python3 - "$INCIDENT_AT" "$WINDOW_MINUTES" <<'PY'
import datetime as dt
import re
import sys

incident_at, raw_window = sys.argv[1:]
if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", incident_at):
    raise SystemExit("incident_at must use canonical YYYY-MM-DDTHH:MM:SSZ format")
try:
    parsed = dt.datetime.strptime(incident_at, "%Y-%m-%dT%H:%M:%SZ")
except ValueError as error:
    raise SystemExit("incident_at is invalid") from error
if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != incident_at:
    raise SystemExit("incident_at is not canonical")
if raw_window not in {"5", "15", "30", "60"}:
    raise SystemExit("window_minutes is outside the allowlist")
PY

[[ -f "$CONF" && ! -L "$CONF" ]] || fail "origin incident evidence registration is missing"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "registration ownership is invalid"
[[ "$(stat -c '%a' "$CONF")" == '600' ]] || fail "registration permissions are invalid"
# shellcheck disable=SC1090
source "$CONF"

[[ "${audit_name:-}" == 'origin-incident-evidence' ]] || fail "registration name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested SHA is not registered"
[[ "${collector_path:-}" == '/usr/local/libexec/hermes-deals-audits/origin-incident-evidence.py' ]] || fail "registered collector path is invalid"
[[ "${collector_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered collector SHA is invalid"
[[ "${dispatcher_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered dispatcher SHA is invalid"
[[ "${workflow_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered workflow SHA is invalid"
[[ "${origin_port:-}" == '9128' ]] || fail "origin port registration mismatch"
[[ "${allowed_windows:-}" == '5,15,30,60' ]] || fail "window allowlist registration mismatch"

[[ -f "$collector_path" && ! -L "$collector_path" ]] || fail "registered collector is missing or unsafe"
[[ "$(stat -c '%U:%G' "$collector_path")" == 'root:root' ]] || fail "collector ownership is invalid"
[[ "$(sha256sum "$collector_path" | awk '{print $1}')" == "$collector_sha256" ]] || fail "collector content drift"
self_path="$(readlink -f -- "$0")"
[[ "$self_path" == '/usr/local/sbin/hermes-deals-origin-incident-evidence-dispatch' ]] || fail "dispatcher path is invalid"
[[ "$(stat -c '%U:%G' "$self_path")" == 'root:root' ]] || fail "dispatcher ownership is invalid"
[[ "$(sha256sum "$self_path" | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail "dispatcher content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-origin-incident-evidence-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

run_key="$(basename -- "$EXPORT_DIR")"
[[ "$run_key" =~ ^hermes-deals-origin-incident-evidence-[0-9]+-[0-9]+$ ]] || fail "unexpected artifact directory name"
staging="$STAGING_ROOT/$run_key"
install -d -o root -g root -m 0700 "$STAGING_ROOT"
[[ ! -e "$staging" ]] || fail "staging directory already exists"
install -d -o root -g root -m 0700 "$staging"
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT

set +e
/usr/bin/env -i \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 \
  /usr/bin/python3 "$collector_path" \
    --incident-at "$INCIDENT_AT" \
    --window-minutes "$WINDOW_MINUTES" \
    --output "$staging/incident-evidence.json" \
  > "$staging/collector-stdout.txt" \
  2> "$staging/collector-stderr.txt"
collector_rc=$?
set -e

[[ "$collector_rc" =~ ^[0-9]+$ ]] || fail "collector exit code is invalid"
destination="$EXPORT_DIR/audit-evidence"
python3 - "$staging" "$destination" "$EXPECTED_SHA" "$INCIDENT_AT" "$WINDOW_MINUTES" "$collector_rc" <<'PY'
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
commit_sha = sys.argv[3]
incident_at = sys.argv[4]
window_minutes = int(sys.argv[5])
collector_rc = int(sys.argv[6])

SIGNATURE_KEYS = {
    "gateway_502",
    "upstream_failure",
    "timeout",
    "connection_reset",
    "database",
    "exception",
    "oom",
    "reconnect",
}
RUN_STATUSES = {
    "ok",
    "empty",
    "command_missing",
    "timeout",
    "nonzero",
    "output_limit",
    "parse_error",
    "not_applicable",
}
SERVICE_ROLES = {"api", "web", "db", "cloudflared"}
PARTIAL_REASONS = {
    "docker_inventory_unavailable",
    "api_container_ambiguous",
    "web_container_ambiguous",
    "db_container_ambiguous",
    "cloudflared_container_ambiguous",
    "api_inspect_unavailable",
    "web_inspect_unavailable",
    "db_inspect_unavailable",
    "cloudflared_inspect_unavailable",
    "api_logs_incomplete",
    "web_logs_incomplete",
    "db_logs_incomplete",
    "cloudflared_logs_incomplete",
    "kernel_journal_unavailable",
    "system_journal_unavailable",
}
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def canonical_timestamp(value):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise SystemExit("unsafe or non-canonical timestamp")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise SystemExit("invalid timestamp") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise SystemExit("timestamp is not canonical")


def bounded_int(value, maximum=10**15):
    if type(value) is not int or value < 0 or value > maximum:
        raise SystemExit("integer value is outside bounds")


def validate_counts(value):
    if not isinstance(value, dict) or set(value) != SIGNATURE_KEYS:
        raise SystemExit("signature counter schema mismatch")
    for count in value.values():
        bounded_int(count, 10**9)


def validate_state(value):
    if value is None:
        return
    required = {
        "status",
        "running",
        "restarting",
        "oom_killed",
        "dead",
        "exit_code",
        "restart_count",
        "health_status",
        "started_at",
        "finished_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SystemExit("service state schema mismatch")
    if value["status"] not in {"created", "running", "paused", "restarting", "removing", "exited", "dead", "unknown"}:
        raise SystemExit("service status is invalid")
    if value["health_status"] not in {"none", "starting", "healthy", "unhealthy", "unknown"}:
        raise SystemExit("health status is invalid")
    for key in ("running", "restarting", "oom_killed", "dead"):
        if type(value[key]) is not bool:
            raise SystemExit("service state boolean is invalid")
    if value["exit_code"] is not None:
        bounded_int(value["exit_code"], 255)
    bounded_int(value["restart_count"], 1_000_000)
    for key in ("started_at", "finished_at"):
        stamp = value[key]
        if stamp is not None and (
            not isinstance(stamp, str)
            or len(stamp) > 64
            or "\r" in stamp
            or "\n" in stamp
        ):
            raise SystemExit("unsafe service timestamp")


manifest = {
    "schema_version": 1,
    "audit": "origin-incident-evidence",
    "commit_sha": commit_sha,
    "incident_at": incident_at,
    "window_minutes": window_minutes,
    "collector_exit_code": collector_rc,
    "sanitization_passed": False,
    "production_apply_authorized": False,
    "production_database_read": False,
    "production_database_write": False,
    "production_deployment": False,
    "restart_or_configuration_mutation": False,
    "raw_logs_uploaded": False,
}
destination.mkdir(mode=0o700, parents=False, exist_ok=False)
report_path = source / "incident-evidence.json"
if not report_path.is_file() or report_path.is_symlink():
    manifest["error"] = "collector_report_missing"
else:
    if report_path.stat().st_size > 1024 * 1024:
        raise SystemExit("collector report exceeds 1 MiB")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if set(report) != {
        "schema_version",
        "captured_at",
        "incident_at",
        "window",
        "collection_status",
        "partial_reasons",
        "host",
        "services",
        "kernel",
        "system_journal",
        "collection",
    }:
        raise SystemExit("unexpected collector report fields")
    if report["schema_version"] != "1" or report["incident_at"] != incident_at:
        raise SystemExit("collector report identity mismatch")
    canonical_timestamp(report["captured_at"])
    canonical_timestamp(report["incident_at"])

    window = report["window"]
    if not isinstance(window, dict) or set(window) != {"minutes", "start", "end"}:
        raise SystemExit("window schema mismatch")
    if window["minutes"] != window_minutes:
        raise SystemExit("window minutes mismatch")
    canonical_timestamp(window["start"])
    canonical_timestamp(window["end"])

    status = report["collection_status"]
    if status not in {"complete", "partial"}:
        raise SystemExit("collection status is invalid")
    reasons = report["partial_reasons"]
    if not isinstance(reasons, list) or reasons != sorted(set(reasons)) or not set(reasons).issubset(PARTIAL_REASONS):
        raise SystemExit("partial reason allowlist mismatch")
    if (status == "complete") != (not reasons):
        raise SystemExit("collection status and partial reasons disagree")
    expected_rc = 0 if status == "complete" else 2
    if collector_rc != expected_rc:
        raise SystemExit("collector exit code and status disagree")

    host = report["host"]
    if not isinstance(host, dict) or set(host) != {
        "uptime_seconds",
        "load_average",
        "memory_bytes",
        "root_filesystem_bytes",
        "origin_listener",
    }:
        raise SystemExit("host schema mismatch")
    bounded_int(host["uptime_seconds"], 10**9)
    loads = host["load_average"]
    if not isinstance(loads, list) or len(loads) != 3:
        raise SystemExit("load average schema mismatch")
    for value in loads:
        if type(value) not in {int, float} or value < 0 or value > 100000:
            raise SystemExit("load average value is invalid")
    for section in ("memory_bytes", "root_filesystem_bytes"):
        values = host[section]
        expected = {"total", "available", "swap_total", "swap_free"} if section == "memory_bytes" else {"total", "free", "available"}
        if not isinstance(values, dict) or set(values) != expected:
            raise SystemExit("host byte counter schema mismatch")
        for value in values.values():
            bounded_int(value)
    listener = host["origin_listener"]
    if not isinstance(listener, dict) or set(listener) != {"port", "listening"}:
        raise SystemExit("origin listener schema mismatch")
    if listener["port"] != 9128 or type(listener["listening"]) is not bool:
        raise SystemExit("origin listener value mismatch")

    services = report["services"]
    if not isinstance(services, dict) or set(services) != SERVICE_ROLES:
        raise SystemExit("service role schema mismatch")
    service_fields = {
        "present",
        "ambiguous",
        "inspect_status",
        "state",
        "log_status",
        "log_truncated",
        "log_signature_counts",
    }
    for role in sorted(SERVICE_ROLES):
        item = services[role]
        if not isinstance(item, dict) or set(item) != service_fields:
            raise SystemExit("service evidence schema mismatch")
        for key in ("present", "ambiguous", "log_truncated"):
            if type(item[key]) is not bool:
                raise SystemExit("service evidence boolean is invalid")
        if item["inspect_status"] not in RUN_STATUSES or item["log_status"] not in RUN_STATUSES:
            raise SystemExit("service command status is invalid")
        validate_state(item["state"])
        validate_counts(item["log_signature_counts"])

    kernel = report["kernel"]
    if not isinstance(kernel, dict) or set(kernel) != {"status", "truncated", "oom_signature_count"}:
        raise SystemExit("kernel evidence schema mismatch")
    if kernel["status"] not in RUN_STATUSES or type(kernel["truncated"]) is not bool:
        raise SystemExit("kernel evidence status is invalid")
    bounded_int(kernel["oom_signature_count"], 10**9)

    journal = report["system_journal"]
    if not isinstance(journal, dict) or set(journal) != {"status", "truncated", "signature_counts"}:
        raise SystemExit("system journal schema mismatch")
    if journal["status"] not in RUN_STATUSES or type(journal["truncated"]) is not bool:
        raise SystemExit("system journal status is invalid")
    validate_counts(journal["signature_counts"])

    collection = report["collection"]
    if not isinstance(collection, dict) or set(collection) != {
        "docker_available",
        "docker_inventory_status",
        "command_timeout_seconds",
        "max_command_bytes",
    }:
        raise SystemExit("collection metadata schema mismatch")
    if type(collection["docker_available"]) is not bool:
        raise SystemExit("docker availability flag is invalid")
    if collection["docker_inventory_status"] not in RUN_STATUSES:
        raise SystemExit("docker inventory status is invalid")
    if collection["command_timeout_seconds"] != 12 or collection["max_command_bytes"] != 2 * 1024 * 1024:
        raise SystemExit("collection bounds mismatch")

    canonical = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    target = destination / "incident-evidence.json"
    target.write_text(canonical, encoding="utf-8")
    os.chmod(target, 0o600)
    manifest.update(
        {
            "collection_status": status,
            "report_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "sanitization_passed": True,
        }
    )

manifest_path = destination / "dispatcher-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(manifest_path, 0o600)
exit_path = destination / "audit-exit-code.txt"
exit_path.write_text(f"{collector_rc}\n", encoding="utf-8")
os.chmod(exit_path, 0o600)
PY

chown -R github-runner:github-runner "$destination"
find "$destination" -type d -exec chmod 0700 {} +
find "$destination" -type f -exec chmod 0600 {} +
printf 'AUDIT=origin-incident-evidence\nREGISTERED_COMMIT=%s\nINCIDENT_AT=%s\nWINDOW_MINUTES=%s\nCOLLECTOR_EXIT_CODE=%s\n' \
  "$EXPECTED_SHA" "$INCIDENT_AT" "$WINDOW_MINUTES" "$collector_rc"
printf 'PRODUCTION_DATABASE_READ=false\nPRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\nRESTART_OR_CONFIGURATION_MUTATION=false\nRAW_LOGS_UPLOADED=false\n'
exit "$collector_rc"
