#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit

EXPECTED_HOSTNAME = "deals.rozkalns.net"
EXPECTED_SCHEME = "http"
EXPECTED_HOST = "192.168.0.180"
EXPECTED_PORT = 9128
EXPECTED_PATH = ""
EXPECTED_SERVICE = "http://192.168.0.180:9128"
HEALTH_PATH = "/api/health"
COMMAND_TIMEOUT_SECONDS = 8
HTTP_TIMEOUT_SECONDS = 5
MAX_COMMAND_OUTPUT = 2 * 1024 * 1024
MAX_CONFIG_BYTES = 256 * 1024
MAX_REPORT_BYTES = 1024 * 1024

SOURCE_VALUES = {"local_config", "remote_config_log", "runtime_args", "runtime_env"}
CONTAINER_STATES = {
    "created", "running", "paused", "restarting", "removing", "exited", "dead",
    "unknown",
}
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


@dataclasses.dataclass(frozen=True)
class CommandResult:
    status: str
    stdout: str
    truncated: bool
    returncode: int | None


@dataclasses.dataclass(frozen=True)
class Candidate:
    source: str
    hostname: str | None
    service: str
    terminal_404_present: bool | None
    authoritative: bool


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_command(
    args: list[str],
    *,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    maximum: int = MAX_COMMAND_OUTPUT,
    merge_stderr: bool = False,
) -> CommandResult:
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            },
        )
    except FileNotFoundError:
        return CommandResult("command_missing", "", False, None)
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, _stderr = process.communicate()
        return CommandResult(
            "timeout",
            stdout[:maximum].decode("utf-8", errors="replace"),
            len(stdout) > maximum,
            None,
        )
    truncated = len(stdout) > maximum
    text = stdout[:maximum].decode("utf-8", errors="replace")
    if truncated:
        return CommandResult("output_limit", text, True, process.returncode)
    if process.returncode != 0:
        return CommandResult("nonzero", text, False, process.returncode)
    return CommandResult("ok" if text.strip() else "empty", text, False, 0)


def strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        if value[0] == '"':
            try:
                decoded = json.loads(value)
                return decoded if isinstance(decoded, str) else value[1:-1]
            except json.JSONDecodeError:
                return value[1:-1]
        return value[1:-1].replace("''", "'")
    return value


def parse_ingress_yaml(
    text: str,
    source: str = "local_config",
) -> tuple[list[Candidate], bool]:
    if source not in SOURCE_VALUES:
        raise ValueError("unsupported candidate source")
    entries: list[dict[str, str | None]] = []
    current: dict[str, str | None] | None = None
    active = False
    base_indent = 0
    for raw in text.splitlines():
        if "\x00" in raw:
            continue
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)
        if not active:
            if re.fullmatch(r"ingress\s*:\s*(?:#.*)?", stripped):
                active, base_indent = True, indent
            continue
        if indent <= base_indent and not stripped.startswith("-"):
            break
        if stripped.startswith("-"):
            if current is not None:
                entries.append(current)
            current = {"hostname": None, "service": None}
            stripped = stripped[1:].strip()
        if current is None or not stripped:
            continue
        match = re.fullmatch(
            r"(hostname|service)\s*:\s*(.*?)\s*(?:#.*)?",
            stripped,
        )
        if match:
            current[match.group(1)] = strip_scalar(match.group(2))
    if current is not None:
        entries.append(current)
    terminal = any(
        not entry.get("hostname")
        and str(entry.get("service") or "").strip().lower() == "http_status:404"
        for entry in entries
    )
    candidates = [
        Candidate(
            source,
            str(entry["hostname"]).strip() if entry.get("hostname") else None,
            str(entry["service"]).strip(),
            terminal,
            True,
        )
        for entry in entries
        if entry.get("service")
        and str(entry.get("service")).strip().lower() != "http_status:404"
    ]
    return candidates, bool(entries)


def candidates_from_json_config(
    value: Any,
    source: str = "remote_config_log",
) -> tuple[list[Candidate], bool]:
    ingress = value.get("ingress") if isinstance(value, dict) else None
    if source not in SOURCE_VALUES or not isinstance(ingress, list):
        return [], False
    terminal = any(
        isinstance(entry, dict)
        and not entry.get("hostname")
        and str(entry.get("service") or "").strip().lower() == "http_status:404"
        for entry in ingress
    )
    result: list[Candidate] = []
    for entry in ingress:
        if not isinstance(entry, dict):
            continue
        service = str(entry.get("service") or "").strip()
        if not service or service.lower() == "http_status:404":
            continue
        hostname = str(entry.get("hostname") or "").strip() or None
        result.append(Candidate(source, hostname, service, terminal, True))
    return result, True


def parse_remote_config_logs(text: str) -> tuple[list[Candidate], bool]:
    decoder = json.JSONDecoder()
    found: list[Candidate] = []
    authoritative = False
    for line in text.splitlines():
        start = 0
        while (index := line.find("config=", start)) >= 0:
            raw = line[index + 7:].lstrip()
            try:
                value, consumed = decoder.raw_decode(raw)
            except json.JSONDecodeError:
                start = index + 7
                continue
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    start = index + 7 + consumed
                    continue
            candidates, seen = candidates_from_json_config(value)
            found.extend(candidates)
            authoritative = authoritative or seen
            start = index + 7 + consumed
    return found, authoritative


def option_value(tokens: list[str], option: str) -> str | None:
    for index, token in enumerate(tokens):
        if token == option and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(option + "="):
            return token[len(option) + 1:]
    return None


def runtime_candidates(
    inspect: dict[str, Any],
) -> tuple[list[Candidate], set[str], list[str]]:
    config = inspect.get("Config") if isinstance(inspect.get("Config"), dict) else {}
    tokens: list[str] = []
    if isinstance(inspect.get("Path"), str):
        tokens.append(inspect["Path"])
    for value in (inspect.get("Args"), config.get("Cmd")):
        if isinstance(value, list):
            tokens.extend(str(item) for item in value if isinstance(item, (str, int)))
    paths: list[str] = []
    explicit = option_value(tokens, "--config")
    if explicit in {"/etc/cloudflared/config.yml", "/etc/cloudflared/config.yaml"}:
        paths.append(explicit)
    mounts = inspect.get("Mounts")
    if isinstance(mounts, list):
        for mount in mounts:
            destination = mount.get("Destination") if isinstance(mount, dict) else None
            if destination in {"/etc/cloudflared/config.yml", "/etc/cloudflared/config.yaml"}:
                if destination not in paths:
                    paths.append(destination)
            elif destination == "/etc/cloudflared":
                for candidate in ("/etc/cloudflared/config.yml", "/etc/cloudflared/config.yaml"):
                    if candidate not in paths:
                        paths.append(candidate)
    result: list[Candidate] = []
    url = option_value(tokens, "--url")
    hostname = option_value(tokens, "--hostname")
    if url:
        result.append(
            Candidate("runtime_args", hostname.strip() if hostname else None, url.strip(), None, bool(hostname))
        )
    env_values: dict[str, str] = {}
    for item in config.get("Env") or []:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if key in {"TUNNEL_ORIGIN_URL", "TUNNEL_URL", "TUNNEL_HOSTNAME"}:
                env_values[key] = value
    env_url = env_values.get("TUNNEL_ORIGIN_URL") or env_values.get("TUNNEL_URL")
    env_hostname = env_values.get("TUNNEL_HOSTNAME")
    if env_url:
        result.append(
            Candidate(
                "runtime_env",
                env_hostname.strip() if env_hostname else None,
                env_url.strip(),
                None,
                bool(env_hostname),
            )
        )
    return result, {"runtime_args", "runtime_env"}, paths


def safe_config_from_mount(
    inspect: dict[str, Any],
    container_id: str,
    destination: str,
) -> tuple[str | None, str]:
    if destination not in {"/etc/cloudflared/config.yml", "/etc/cloudflared/config.yaml"}:
        return None, "not_applicable"
    for mount in inspect.get("Mounts") or []:
        if not isinstance(mount, dict):
            continue
        source = mount.get("Source")
        target = mount.get("Destination")
        if not isinstance(source, str) or not source.startswith("/"):
            continue
        if target == destination:
            path = Path(source)
        elif target == "/etc/cloudflared":
            path = Path(source) / Path(destination).name
        else:
            continue
        try:
            metadata = path.lstat()
            if path.is_symlink() or not path.is_file():
                return None, "parse_error"
            if metadata.st_size > MAX_CONFIG_BYTES:
                return None, "output_limit"
            return path.read_text(encoding="utf-8", errors="strict"), "ok"
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError):
            return None, "nonzero"
    result = run_command(
        ["docker", "exec", container_id, "cat", "--", destination],
        maximum=MAX_CONFIG_BYTES,
    )
    return (result.stdout if result.status == "ok" else None), result.status


def service_kind(service: str) -> str:
    lowered = service.strip().lower()
    if lowered.startswith(("http://", "https://")):
        return "http_origin"
    if lowered.startswith("http_status:"):
        return "http_status"
    if lowered == "hello_world":
        return "hello_world"
    if lowered.startswith("ssh://"):
        return "ssh"
    if lowered.startswith(("tcp://", "unix:")):
        return "tcp"
    return "other" if ":" in lowered else "invalid"


def host_class(hostname: str | None) -> str:
    if not hostname:
        return "unknown"
    lowered = hostname.rstrip(".").lower()
    if lowered == EXPECTED_HOST:
        return "expected"
    if lowered in {"localhost", "ip6-localhost"}:
        return "loopback"
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return "dns_name"
    if address.is_loopback:
        return "loopback"
    return "private_other" if address.is_private else "public_ip"


def normalize_http_service(service: str) -> dict[str, Any]:
    kind = service_kind(service)
    empty = {
        "service_kind": kind,
        "observed_scheme": "unknown",
        "observed_host_class": "unknown",
        "observed_port": None,
        "scheme_match": False,
        "host_match": False,
        "port_match": False,
        "path_match": False,
        "exact_service_match": False,
    }
    if kind != "http_origin":
        return empty
    try:
        parsed = urlsplit(service)
        scheme = parsed.scheme.lower()
        port = parsed.port or (80 if scheme == "http" else 443 if scheme == "https" else None)
    except (TypeError, ValueError):
        empty["service_kind"] = "invalid"
        return empty
    row = {
        "service_kind": "http_origin",
        "observed_scheme": scheme if scheme in {"http", "https"} else "other",
        "observed_host_class": host_class(parsed.hostname),
        "observed_port": port if isinstance(port, int) and 1 <= port <= 65535 else None,
        "scheme_match": scheme == EXPECTED_SCHEME,
        "host_match": (parsed.hostname or "").rstrip(".").lower() == EXPECTED_HOST,
        "port_match": port == EXPECTED_PORT,
        "path_match": (parsed.path or "") in {"", "/"} and not parsed.query and not parsed.fragment,
    }
    row["exact_service_match"] = all(
        row[key] for key in ("scheme_match", "host_match", "port_match", "path_match")
    )
    return row


def evaluate_candidates(
    candidates: list[Candidate],
    *,
    authoritative_config_seen: bool,
) -> dict[str, Any]:
    sources = sorted({item.source for item in candidates if item.source in SOURCE_VALUES})
    matches = [
        item for item in candidates
        if item.hostname and item.hostname.rstrip(".").lower() == EXPECTED_HOSTNAME
    ]
    unbound = [item for item in candidates if not item.hostname]
    if not matches and len(unbound) == 1 and len(candidates) == 1:
        row = normalize_http_service(unbound[0].service)
        return {
            "status": "unbound_single_origin",
            "sources": sources,
            "candidate_count": 1,
            "hostname_entry_present": False,
            **{key: row[key] for key in (
                "exact_service_match", "scheme_match", "host_match", "port_match",
                "path_match", "observed_scheme", "observed_host_class",
                "observed_port", "service_kind",
            )},
            "terminal_404_present": unbound[0].terminal_404_present,
            "authoritative_config_seen": authoritative_config_seen,
        }
    if not matches:
        return {
            "status": "missing",
            "sources": sources,
            "candidate_count": len(candidates),
            "hostname_entry_present": False,
            "exact_service_match": False,
            "scheme_match": None,
            "host_match": None,
            "port_match": None,
            "path_match": None,
            "observed_scheme": "unknown",
            "observed_host_class": "unknown",
            "observed_port": None,
            "service_kind": "invalid",
            "terminal_404_present": None,
            "authoritative_config_seen": authoritative_config_seen,
        }
    rows = [normalize_http_service(item.service) for item in matches]
    signatures = {
        tuple(row[key] for key in (
            "service_kind", "observed_scheme", "observed_host_class",
            "observed_port", "scheme_match", "host_match", "port_match",
            "path_match", "exact_service_match",
        ))
        for row in rows
    }
    if len(signatures) != 1:
        return {
            "status": "ambiguous",
            "sources": sources,
            "candidate_count": len(candidates),
            "hostname_entry_present": True,
            "exact_service_match": False,
            "scheme_match": None,
            "host_match": None,
            "port_match": None,
            "path_match": None,
            "observed_scheme": "unknown",
            "observed_host_class": "unknown",
            "observed_port": None,
            "service_kind": "invalid",
            "terminal_404_present": None,
            "authoritative_config_seen": authoritative_config_seen,
        }
    row = rows[0]
    terminals = {item.terminal_404_present for item in matches}
    return {
        "status": "exact" if row["exact_service_match"] else "mismatch",
        "sources": sources,
        "candidate_count": len(candidates),
        "hostname_entry_present": True,
        **{key: row[key] for key in (
            "exact_service_match", "scheme_match", "host_match", "port_match",
            "path_match", "observed_scheme", "observed_host_class",
            "observed_port", "service_kind",
        )},
        "terminal_404_present": next(iter(terminals)) if len(terminals) == 1 else None,
        "authoritative_config_seen": authoritative_config_seen,
    }


def docker_inventory() -> tuple[list[dict[str, Any]], CommandResult]:
    result = run_command(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"])
    if result.status not in {"ok", "empty"}:
        return [], result
    try:
        return [
            value for line in result.stdout.splitlines()
            if line.strip() and isinstance((value := json.loads(line)), dict)
        ], result
    except json.JSONDecodeError:
        return [], CommandResult("parse_error", "", result.truncated, result.returncode)


def find_cloudflared(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if "cloudflared" in str(row.get("Image") or "").lower()
        or "cloudflared" in str(row.get("Names") or "").lower()
    ]


def inspect_container(container_id: str) -> tuple[dict[str, Any] | None, CommandResult]:
    result = run_command(["docker", "inspect", container_id])
    if result.status != "ok":
        return None, result
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return None, CommandResult("parse_error", "", result.truncated, result.returncode)
    return value[0], result


def container_state(inspect: dict[str, Any] | None) -> str:
    state = inspect.get("State") if isinstance(inspect, dict) else None
    value = str(state.get("Status") if isinstance(state, dict) else "unknown").lower()
    return value if value in CONTAINER_STATES else "unknown"


def origin_listener() -> tuple[bool | None, str]:
    result = run_command(["ss", "-H", "-ltn", "sport", "=", f":{EXPECTED_PORT}"], maximum=65536)
    if result.status == "ok":
        return bool(result.stdout.strip()), "ok"
    if result.status == "empty":
        return False, "ok"
    return None, result.status


def origin_health() -> dict[str, Any]:
    try:
        connection = http.client.HTTPConnection(EXPECTED_HOST, EXPECTED_PORT, timeout=HTTP_TIMEOUT_SECONDS)
        connection.request(
            "GET",
            HEALTH_PATH,
            headers={
                "Host": EXPECTED_HOSTNAME,
                "Accept": "application/json",
                "User-Agent": "hermes-deals-cloudflare-ingress-audit",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        body = response.read(65537)
        content_type = str(response.getheader("Content-Type") or "").lower()
        connection.close()
    except (OSError, http.client.HTTPException):
        return {
            "status": "unavailable",
            "http_status": None,
            "body_kind": "unavailable",
            "body_truncated": False,
        }
    return {
        "status": "ok",
        "http_status": int(response.status),
        "body_kind": (
            "empty" if not body else "json" if "json" in content_type
            else "text" if content_type.startswith("text/") else "other"
        ),
        "body_truncated": len(body) > 65536,
    }


def collect() -> tuple[dict[str, Any], int]:
    reasons: set[str] = set()
    rows, inventory = docker_inventory()
    matches = find_cloudflared(rows)
    inspect = None
    inspect_result = CommandResult("not_applicable", "", False, None)
    logs_result = CommandResult("not_applicable", "", False, None)
    local_statuses: list[str] = []
    candidates: list[Candidate] = []
    checked: set[str] = set()
    authoritative = False
    if inventory.status not in {"ok", "empty"}:
        reasons.add("docker_inventory_unavailable")
    elif len(matches) == 0:
        reasons.add("cloudflared_container_missing")
    elif len(matches) > 1:
        reasons.add("cloudflared_container_ambiguous")
    else:
        container_id = str(matches[0].get("ID") or "")
        if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
            reasons.add("cloudflared_inspect_unavailable")
        else:
            inspect, inspect_result = inspect_container(container_id)
            if inspect is None:
                reasons.add("cloudflared_inspect_unavailable")
            else:
                runtime, runtime_checked, paths = runtime_candidates(inspect)
                candidates.extend(runtime)
                checked.update(runtime_checked)
                for path in paths:
                    checked.add("local_config")
                    text, status = safe_config_from_mount(inspect, container_id, path)
                    local_statuses.append(status)
                    if text is not None:
                        parsed, seen = parse_ingress_yaml(text)
                        candidates.extend(parsed)
                        authoritative = authoritative or seen
                checked.add("remote_config_log")
                logs_result = run_command(
                    ["docker", "logs", "--since", "168h", "--tail", "5000", container_id],
                    maximum=MAX_COMMAND_OUTPUT,
                    merge_stderr=True,
                )
                if logs_result.status == "ok":
                    parsed, seen = parse_remote_config_logs(logs_result.stdout)
                    candidates.extend(parsed)
                    authoritative = authoritative or seen
    authoritative = authoritative or any(item.authoritative for item in candidates)
    if not authoritative:
        if local_statuses and "ok" not in local_statuses:
            reasons.add("local_config_unavailable")
        if logs_result.status not in {"ok", "empty", "not_applicable"}:
            reasons.add("cloudflared_logs_unavailable")
    mapping = evaluate_candidates(candidates, authoritative_config_seen=authoritative)
    if mapping["status"] in {"missing", "unbound_single_origin"} and not authoritative:
        reasons.add("cloudflared_configuration_unproven")
    listening, listener_status = origin_listener()
    if listener_status != "ok":
        reasons.add("origin_listener_check_unavailable")
    health = origin_health()
    if health["status"] != "ok":
        reasons.add("origin_health_check_unavailable")
    state = container_state(inspect)
    hard_fail = bool(
        inspect is not None
        and (
            state != "running"
            or mapping["status"] in {"mismatch", "ambiguous"}
            or (mapping["status"] == "missing" and authoritative)
            or listening is False
            or (health["status"] == "ok" and health["http_status"] != 200)
        )
    )
    if hard_fail:
        audit_status, exit_code = "fail", 3
    elif reasons:
        audit_status, exit_code = "partial", 2
    elif (
        inspect is not None
        and state == "running"
        and mapping["status"] == "exact"
        and listening is True
        and health["status"] == "ok"
        and health["http_status"] == 200
    ):
        audit_status, exit_code = "pass", 0
    else:
        reasons.add("cloudflared_configuration_unproven")
        audit_status, exit_code = "partial", 2
    report = {
        "schema_version": "1",
        "captured_at": utc_now(),
        "audit_status": audit_status,
        "partial_reasons": sorted(reasons),
        "expected": {
            "hostname": EXPECTED_HOSTNAME,
            "scheme": EXPECTED_SCHEME,
            "host": EXPECTED_HOST,
            "port": EXPECTED_PORT,
            "path": EXPECTED_PATH,
            "service": EXPECTED_SERVICE,
        },
        "cloudflared": {
            "container_count": len(matches),
            "container_unique": len(matches) == 1,
            "state": state,
            "mapping": mapping,
            "sensitive_fields_exported": False,
        },
        "origin": {
            "listener_port": EXPECTED_PORT,
            "listening": listening,
            "listener_status": listener_status,
            "health_path": HEALTH_PATH,
            "health": health,
        },
        "collection": {
            "docker_inventory_status": inventory.status,
            "cloudflared_inspect_status": inspect_result.status,
            "cloudflared_logs_status": logs_result.status,
            "local_config_statuses": sorted(set(local_statuses)),
            "sources_checked": sorted(checked),
            "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "http_timeout_seconds": HTTP_TIMEOUT_SECONDS,
            "command_output_limit_bytes": MAX_COMMAND_OUTPUT,
            "config_limit_bytes": MAX_CONFIG_BYTES,
            "raw_config_exported": False,
            "raw_logs_exported": False,
            "container_identity_exported": False,
            "runtime_args_exported": False,
            "runtime_environment_exported": False,
            "mounts_exported": False,
            "credentials_exported": False,
        },
    }
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    output = Path(parser.parse_args().output)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise SystemExit("output path is invalid or already exists")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise SystemExit("output parent is missing or unsafe")
    report, exit_code = collect()
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise SystemExit("report exceeds maximum size")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
