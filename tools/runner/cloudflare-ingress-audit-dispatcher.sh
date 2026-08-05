#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-cloudflare-ingress-audit-dispatch <registered-sha> <artifact-dir>"

EXPECTED_SHA="$1"
EXPORT_DIR="$2"
CONF='/etc/hermes-deals-audits.d/cloudflare-ingress.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ -f "$CONF" && ! -L "$CONF" ]] || fail "cloudflare ingress audit registration is missing"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "registration ownership is invalid"
[[ "$(stat -c '%a' "$CONF")" == '600' ]] || fail "registration permissions are invalid"
# shellcheck disable=SC1090
source "$CONF"

[[ "${audit_name:-}" == 'cloudflare-ingress' ]] || fail "registration name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested SHA is not registered"
[[ "${collector_path:-}" == '/usr/local/libexec/hermes-deals-audits/cloudflare-ingress-audit.py' ]] || fail "registered collector path is invalid"
[[ "${collector_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered collector SHA is invalid"
[[ "${dispatcher_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered dispatcher SHA is invalid"
[[ "${workflow_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered workflow SHA is invalid"
[[ "${expected_hostname:-}" == 'deals.rozkalns.net' ]] || fail "registered hostname mismatch"
[[ "${expected_service:-}" == 'http://192.168.0.180:9128' ]] || fail "registered service mismatch"
[[ "${expected_health_path:-}" == '/api/health' ]] || fail "registered health path mismatch"

[[ -f "$collector_path" && ! -L "$collector_path" ]] || fail "registered collector is missing or unsafe"
[[ "$(stat -c '%U:%G' "$collector_path")" == 'root:root' ]] || fail "collector ownership is invalid"
[[ "$(sha256sum "$collector_path" | awk '{print $1}')" == "$collector_sha256" ]] || fail "collector content drift"
self_path="$(readlink -f -- "$0")"
[[ "$self_path" == '/usr/local/sbin/hermes-deals-cloudflare-ingress-audit-dispatch' ]] || fail "dispatcher path is invalid"
[[ "$(stat -c '%U:%G' "$self_path")" == 'root:root' ]] || fail "dispatcher ownership is invalid"
[[ "$(sha256sum "$self_path" | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail "dispatcher content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-cloudflare-ingress-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

run_key="$(basename -- "$EXPORT_DIR")"
[[ "$run_key" =~ ^hermes-deals-cloudflare-ingress-[0-9]+-[0-9]+$ ]] || fail "unexpected artifact directory name"
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
    --output "$staging/ingress-audit.json" \
  > "$staging/collector-stdout.txt" \
  2> "$staging/collector-stderr.txt"
collector_rc=$?
set -e

[[ "$collector_rc" =~ ^(0|2|3)$ ]] || fail "collector exit code is outside the allowlist"
destination="$EXPORT_DIR/audit-evidence"

python3 - "$staging" "$destination" "$EXPECTED_SHA" "$collector_rc" <<'PY'
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
commit_sha = sys.argv[3]
collector_rc = int(sys.argv[4])

EXPECTED = {
    "hostname": "deals.rozkalns.net",
    "scheme": "http",
    "host": "192.168.0.180",
    "port": 9128,
    "path": "",
    "service": "http://192.168.0.180:9128",
}
EXPECTED_HEALTH_PATH = "/api/health"
COMMAND_STATUSES = {
    "ok",
    "empty",
    "command_missing",
    "timeout",
    "nonzero",
    "output_limit",
    "parse_error",
    "not_applicable",
}
CONTAINER_STATES = {
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
    "unknown",
}
MAPPING_STATUSES = {
    "exact",
    "mismatch",
    "missing",
    "ambiguous",
    "unbound_single_origin",
}
SOURCE_VALUES = {
    "local_config",
    "remote_config_log",
    "runtime_args",
    "runtime_env",
}
SCHEMES = {"http", "https", "other", "unknown"}
HOST_CLASSES = {
    "expected",
    "loopback",
    "private_other",
    "public_ip",
    "dns_name",
    "unknown",
}
SERVICE_KINDS = {
    "http_origin",
    "http_status",
    "hello_world",
    "ssh",
    "tcp",
    "other",
    "invalid",
}
HEALTH_BODY_KINDS = {"json", "text", "other", "empty", "unavailable"}
PARTIAL_REASONS = {
    "docker_inventory_unavailable",
    "cloudflared_container_missing",
    "cloudflared_container_ambiguous",
    "cloudflared_inspect_unavailable",
    "cloudflared_configuration_unproven",
    "cloudflared_logs_unavailable",
    "local_config_unavailable",
    "origin_listener_check_unavailable",
    "origin_health_check_unavailable",
}
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def canonical_timestamp(value):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise SystemExit("unsafe or non-canonical timestamp")
    parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise SystemExit("timestamp is not canonical")


def bounded_int(value, minimum=0, maximum=10**15):
    if type(value) is not int or not minimum <= value <= maximum:
        raise SystemExit("integer value is outside bounds")


def optional_bool(value):
    if value is not None and type(value) is not bool:
        raise SystemExit("optional boolean is invalid")


report_path = source / "ingress-audit.json"
if not report_path.is_file() or report_path.is_symlink():
    raise SystemExit("collector report is missing or unsafe")
if report_path.stat().st_size > 1024 * 1024:
    raise SystemExit("collector report exceeds 1 MiB")
report = json.loads(report_path.read_text(encoding="utf-8"))

if set(report) != {
    "schema_version",
    "captured_at",
    "audit_status",
    "partial_reasons",
    "expected",
    "cloudflared",
    "origin",
    "collection",
}:
    raise SystemExit("unexpected collector report fields")
if report["schema_version"] != "1":
    raise SystemExit("collector schema mismatch")
canonical_timestamp(report["captured_at"])
if report["audit_status"] not in {"pass", "fail", "partial"}:
    raise SystemExit("audit status is invalid")
expected_rc = {"pass": 0, "partial": 2, "fail": 3}[report["audit_status"]]
if collector_rc != expected_rc:
    raise SystemExit("collector exit code and status disagree")

reasons = report["partial_reasons"]
if not isinstance(reasons, list) or reasons != sorted(set(reasons)):
    raise SystemExit("partial reasons must be unique and sorted")
if not set(reasons).issubset(PARTIAL_REASONS):
    raise SystemExit("partial reason allowlist mismatch")
if report["audit_status"] == "pass" and reasons:
    raise SystemExit("PASS report cannot include partial reasons")
if report["expected"] != EXPECTED:
    raise SystemExit("fixed expected target mismatch")

cloudflared = report["cloudflared"]
if not isinstance(cloudflared, dict) or set(cloudflared) != {
    "container_count",
    "container_unique",
    "state",
    "mapping",
    "sensitive_fields_exported",
}:
    raise SystemExit("cloudflared schema mismatch")
bounded_int(cloudflared["container_count"], 0, 100)
if type(cloudflared["container_unique"]) is not bool:
    raise SystemExit("container uniqueness is invalid")
if cloudflared["container_unique"] != (cloudflared["container_count"] == 1):
    raise SystemExit("container count and uniqueness disagree")
if cloudflared["state"] not in CONTAINER_STATES:
    raise SystemExit("container state is invalid")
if cloudflared["sensitive_fields_exported"] is not False:
    raise SystemExit("sensitive fields export marker is invalid")

mapping = cloudflared["mapping"]
if not isinstance(mapping, dict) or set(mapping) != {
    "status",
    "sources",
    "candidate_count",
    "hostname_entry_present",
    "exact_service_match",
    "scheme_match",
    "host_match",
    "port_match",
    "path_match",
    "observed_scheme",
    "observed_host_class",
    "observed_port",
    "service_kind",
    "terminal_404_present",
    "authoritative_config_seen",
}:
    raise SystemExit("mapping schema mismatch")
if mapping["status"] not in MAPPING_STATUSES:
    raise SystemExit("mapping status is invalid")
sources = mapping["sources"]
if not isinstance(sources, list) or sources != sorted(set(sources)):
    raise SystemExit("mapping sources must be unique and sorted")
if not set(sources).issubset(SOURCE_VALUES):
    raise SystemExit("mapping source allowlist mismatch")
bounded_int(mapping["candidate_count"], 0, 10000)
for key in ("hostname_entry_present", "exact_service_match", "authoritative_config_seen"):
    if type(mapping[key]) is not bool:
        raise SystemExit("mapping boolean is invalid")
for key in ("scheme_match", "host_match", "port_match", "path_match", "terminal_404_present"):
    optional_bool(mapping[key])
if mapping["observed_scheme"] not in SCHEMES:
    raise SystemExit("observed scheme is invalid")
if mapping["observed_host_class"] not in HOST_CLASSES:
    raise SystemExit("observed host class is invalid")
if mapping["observed_port"] is not None:
    bounded_int(mapping["observed_port"], 1, 65535)
if mapping["service_kind"] not in SERVICE_KINDS:
    raise SystemExit("service kind is invalid")
if mapping["status"] == "exact":
    if not all(
        mapping[key] is True
        for key in (
            "hostname_entry_present",
            "exact_service_match",
            "scheme_match",
            "host_match",
            "port_match",
            "path_match",
        )
    ):
        raise SystemExit("exact mapping components disagree")
if mapping["status"] == "ambiguous" and any(
    mapping[key] is not None
    for key in ("scheme_match", "host_match", "port_match", "path_match")
):
    raise SystemExit("ambiguous mapping leaked component observations")

origin = report["origin"]
if not isinstance(origin, dict) or set(origin) != {
    "listener_port",
    "listening",
    "listener_status",
    "health_path",
    "health",
}:
    raise SystemExit("origin schema mismatch")
if origin["listener_port"] != 9128:
    raise SystemExit("listener port mismatch")
optional_bool(origin["listening"])
if origin["listener_status"] not in COMMAND_STATUSES:
    raise SystemExit("listener status is invalid")
if origin["health_path"] != EXPECTED_HEALTH_PATH:
    raise SystemExit("health path mismatch")
health = origin["health"]
if not isinstance(health, dict) or set(health) != {
    "status",
    "http_status",
    "body_kind",
    "body_truncated",
}:
    raise SystemExit("health schema mismatch")
if health["status"] not in {"ok", "unavailable"}:
    raise SystemExit("health status is invalid")
if health["http_status"] is not None:
    bounded_int(health["http_status"], 100, 599)
if health["body_kind"] not in HEALTH_BODY_KINDS:
    raise SystemExit("health body kind is invalid")
if type(health["body_truncated"]) is not bool:
    raise SystemExit("health truncation marker is invalid")

collection = report["collection"]
if not isinstance(collection, dict) or set(collection) != {
    "docker_inventory_status",
    "cloudflared_inspect_status",
    "cloudflared_logs_status",
    "local_config_statuses",
    "sources_checked",
    "command_timeout_seconds",
    "http_timeout_seconds",
    "command_output_limit_bytes",
    "config_limit_bytes",
    "raw_config_exported",
    "raw_logs_exported",
    "container_identity_exported",
    "runtime_args_exported",
    "runtime_environment_exported",
    "mounts_exported",
    "credentials_exported",
}:
    raise SystemExit("collection schema mismatch")
for key in (
    "docker_inventory_status",
    "cloudflared_inspect_status",
    "cloudflared_logs_status",
):
    if collection[key] not in COMMAND_STATUSES:
        raise SystemExit("collection command status is invalid")
local_statuses = collection["local_config_statuses"]
if not isinstance(local_statuses, list) or local_statuses != sorted(set(local_statuses)):
    raise SystemExit("local config statuses must be unique and sorted")
if not set(local_statuses).issubset(COMMAND_STATUSES):
    raise SystemExit("local config status allowlist mismatch")
checked = collection["sources_checked"]
if not isinstance(checked, list) or checked != sorted(set(checked)):
    raise SystemExit("sources checked must be unique and sorted")
if not set(checked).issubset(SOURCE_VALUES):
    raise SystemExit("sources checked allowlist mismatch")
if collection["command_timeout_seconds"] != 8:
    raise SystemExit("command timeout mismatch")
if collection["http_timeout_seconds"] != 5:
    raise SystemExit("HTTP timeout mismatch")
if collection["command_output_limit_bytes"] != 2 * 1024 * 1024:
    raise SystemExit("command output limit mismatch")
if collection["config_limit_bytes"] != 256 * 1024:
    raise SystemExit("config limit mismatch")
for key in (
    "raw_config_exported",
    "raw_logs_exported",
    "container_identity_exported",
    "runtime_args_exported",
    "runtime_environment_exported",
    "mounts_exported",
    "credentials_exported",
):
    if collection[key] is not False:
        raise SystemExit("sensitive export marker is invalid")

destination.mkdir(mode=0o700, parents=False, exist_ok=False)
safe_report = destination / "ingress-audit.json"
safe_report.write_text(
    json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
safe_report.chmod(0o600)
digest = hashlib.sha256(safe_report.read_bytes()).hexdigest()

manifest = {
    "schema_version": 1,
    "audit": "cloudflare-ingress",
    "commit_sha": commit_sha,
    "collector_exit_code": collector_rc,
    "audit_status": report["audit_status"],
    "report_sha256": digest,
    "sanitization_passed": True,
    "production_apply_authorized": False,
    "production_database_read": False,
    "production_database_write": False,
    "production_deployment": False,
    "restart_or_configuration_mutation": False,
    "cloudflare_configuration_mutation": False,
    "raw_config_uploaded": False,
    "raw_logs_uploaded": False,
    "credentials_uploaded": False,
}
manifest_path = destination / "dispatcher-manifest.json"
manifest_path.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
manifest_path.chmod(0o600)
exit_path = destination / "audit-exit-code.txt"
exit_path.write_text(f"{collector_rc}\n", encoding="ascii")
exit_path.chmod(0o600)

if sorted(path.name for path in destination.iterdir()) != [
    "audit-exit-code.txt",
    "dispatcher-manifest.json",
    "ingress-audit.json",
]:
    raise SystemExit("artifact member allowlist mismatch")
PY

chown -R github-runner:github-runner "$destination"
chmod 0700 "$destination"
find "$destination" -maxdepth 1 -type f -exec chmod 0600 {} +

printf 'AUDIT=cloudflare-ingress\nCOMMIT_SHA=%s\nCOLLECTOR_EXIT_CODE=%s\n' \
  "$EXPECTED_SHA" "$collector_rc"
printf 'SANITIZATION_PASSED=true\nRAW_CONFIG_UPLOADED=false\nRAW_LOGS_UPLOADED=false\nCREDENTIALS_UPLOADED=false\n'
printf 'PRODUCTION_DEPLOYMENT=false\nPRODUCTION_DATABASE_READ=false\nPRODUCTION_DATABASE_WRITE=false\n'
printf 'RESTART_OR_CONFIGURATION_MUTATION=false\nCLOUDFLARE_CONFIGURATION_MUTATION=false\n'

exit "$collector_rc"
