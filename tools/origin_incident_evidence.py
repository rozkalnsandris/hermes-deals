#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
from typing import Any, Iterable

SCHEMA_VERSION = "1"
ALLOWED_WINDOWS = {5, 15, 30, 60}
ORIGIN_PORT = 9128
COMMAND_TIMEOUT_SECONDS = 12
MAX_COMMAND_BYTES = 2 * 1024 * 1024
SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}
SERVICE_ROLES = ("api", "web", "db", "cloudflared")
SIGNATURE_PATTERNS: dict[str, re.Pattern[str]] = {
    "gateway_502": re.compile(r"(?:\b502\b|bad gateway|origin_bad_gateway)", re.I),
    "upstream_failure": re.compile(
        r"(?:upstream.{0,80}(?:failed|error|premature|reset|closed)|connect\(\) failed)",
        re.I,
    ),
    "timeout": re.compile(r"(?:timed? out|timeout)", re.I),
    "connection_reset": re.compile(r"(?:connection reset|reset by peer|broken pipe)", re.I),
    "database": re.compile(
        r"(?:postgres|psycopg|sqlalchemy|database.{0,80}(?:error|unavailable|timeout)|connection pool)",
        re.I,
    ),
    "exception": re.compile(r"(?:traceback|exception|uncaught|panic|fatal)", re.I),
    "oom": re.compile(r"(?:out of memory|oom-kill|oomkilled|killed process)", re.I),
    "reconnect": re.compile(r"(?:reconnect|retrying connection|ha connection|connection.{0,40}registered)", re.I),
}
SIGNATURE_KEYS = tuple(SIGNATURE_PATTERNS)
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


class CollectorError(RuntimeError):
    pass


def parse_incident_at(value: str) -> dt.datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise CollectorError("incident_at must use canonical YYYY-MM-DDTHH:MM:SSZ format")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as error:
        raise CollectorError("incident_at is not a valid UTC timestamp") from error
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise CollectorError("incident_at is not canonical")
    return parsed


def parse_window(value: str | int) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError) as error:
        raise CollectorError("window_minutes must be an integer") from error
    if minutes not in ALLOWED_WINDOWS:
        raise CollectorError("window_minutes is outside the allowlist")
    return minutes


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def empty_signature_counts() -> dict[str, int]:
    return {key: 0 for key in SIGNATURE_KEYS}


def count_signatures(text: str) -> dict[str, int]:
    counts = empty_signature_counts()
    for line in text.splitlines():
        for key, pattern in SIGNATURE_PATTERNS.items():
            if pattern.search(line):
                counts[key] += 1
    return counts


def _status_from_returncode(returncode: int, data: bytes) -> str:
    if returncode != 0:
        return "nonzero"
    return "empty" if not data else "ok"


def run_bounded(argv: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS, max_bytes: int = MAX_COMMAND_BYTES) -> dict[str, Any]:
    if not argv or not all(isinstance(part, str) and part for part in argv):
        raise CollectorError("invalid command argv")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=SAFE_ENV,
            close_fds=True,
        )
    except FileNotFoundError:
        return {"status": "command_missing", "returncode": None, "text": "", "truncated": False}

    assert proc.stdout is not None
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + timeout
    status_override: str | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            status_override = "timeout"
            proc.kill()
            break
        ready, _, _ = select.select([proc.stdout], [], [], min(0.2, remaining))
        if ready:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                if proc.poll() is not None:
                    break
                continue
            total += len(chunk)
            if total > max_bytes:
                keep = max(0, len(chunk) - (total - max_bytes))
                if keep:
                    chunks.append(chunk[:keep])
                status_override = "output_limit"
                proc.kill()
                break
            chunks.append(chunk)
        elif proc.poll() is not None:
            break

    try:
        returncode = proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        returncode = proc.wait(timeout=2)
    data = b"".join(chunks)
    status = status_override or _status_from_returncode(returncode, data)
    return {
        "status": status,
        "returncode": returncode,
        "text": data.decode("utf-8", errors="replace"),
        "truncated": status == "output_limit",
    }


def parse_docker_inventory(text: str) -> dict[str, list[str]]:
    inventory = {role: [] for role in SERVICE_ROLES}
    for raw in text.splitlines():
        parts = raw.split("\t")
        if len(parts) != 5:
            continue
        container_id, image, name, project, service = (part.strip() for part in parts)
        if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
            continue
        if project == "hermes-deals" and service in {"api", "web", "db"}:
            inventory[service].append(container_id)
        lower_image = image.lower()
        lower_name = name.lower()
        if "cloudflare/cloudflared" in lower_image or "cloudflared" in lower_name:
            inventory["cloudflared"].append(container_id)
    for role in SERVICE_ROLES:
        inventory[role] = sorted(set(inventory[role]))
    return inventory


def normalize_state(raw_state: dict[str, Any], restart_count: int) -> dict[str, Any]:
    health = raw_state.get("Health") if isinstance(raw_state.get("Health"), dict) else {}
    status = str(raw_state.get("Status") or "unknown").lower()
    if status not in {"created", "running", "paused", "restarting", "removing", "exited", "dead", "unknown"}:
        status = "unknown"
    health_status = str(health.get("Status") or "none").lower()
    if health_status not in {"none", "starting", "healthy", "unhealthy"}:
        health_status = "unknown"

    def safe_timestamp(value: Any) -> str | None:
        if not isinstance(value, str) or not value or value.startswith("0001-"):
            return None
        if len(value) > 64 or "\n" in value or "\r" in value:
            return None
        return value

    exit_code = raw_state.get("ExitCode")
    if type(exit_code) is not int or exit_code < 0 or exit_code > 255:
        exit_code = None
    return {
        "status": status,
        "running": bool(raw_state.get("Running")),
        "restarting": bool(raw_state.get("Restarting")),
        "oom_killed": bool(raw_state.get("OOMKilled")),
        "dead": bool(raw_state.get("Dead")),
        "exit_code": exit_code,
        "restart_count": max(0, min(int(restart_count), 1_000_000)),
        "health_status": health_status,
        "started_at": safe_timestamp(raw_state.get("StartedAt")),
        "finished_at": safe_timestamp(raw_state.get("FinishedAt")),
    }


def parse_state_result(state_result: dict[str, Any], restart_result: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if state_result["status"] not in {"ok", "empty"}:
        return state_result["status"], None
    if restart_result["status"] not in {"ok", "empty"}:
        return restart_result["status"], None
    try:
        raw_state = json.loads(state_result["text"])
        restart_count = int(restart_result["text"].strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return "parse_error", None
    if not isinstance(raw_state, dict):
        return "parse_error", None
    return "ok", normalize_state(raw_state, restart_count)


def service_summary(role: str, candidates: list[str], start: str, end: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "present": bool(candidates),
        "ambiguous": len(candidates) > 1,
        "inspect_status": "not_applicable",
        "state": None,
        "log_status": "not_applicable",
        "log_truncated": False,
        "log_signature_counts": empty_signature_counts(),
    }
    if len(candidates) != 1:
        return summary
    container_id = candidates[0]
    state_result = run_bounded(["docker", "inspect", "--format", "{{json .State}}", container_id])
    restart_result = run_bounded(["docker", "inspect", "--format", "{{.RestartCount}}", container_id])
    inspect_status, state = parse_state_result(state_result, restart_result)
    summary["inspect_status"] = inspect_status
    summary["state"] = state

    log_result = run_bounded(["docker", "logs", "--since", start, "--until", end, container_id])
    summary["log_status"] = log_result["status"]
    summary["log_truncated"] = bool(log_result["truncated"])
    summary["log_signature_counts"] = count_signatures(log_result["text"])
    return summary


def host_metrics() -> dict[str, Any]:
    try:
        uptime_seconds = int(float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        uptime_seconds = 0
    try:
        load_parts = Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3]
        load_average = [round(float(part), 2) for part in load_parts]
        if len(load_average) != 3:
            raise ValueError
    except (OSError, ValueError):
        load_average = [0.0, 0.0, 0.0]

    memory_values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                number = int(value.strip().split()[0]) * 1024
                memory_values[key] = max(0, number)
    except (OSError, ValueError, IndexError):
        pass
    memory = {
        "total": memory_values.get("MemTotal", 0),
        "available": memory_values.get("MemAvailable", 0),
        "swap_total": memory_values.get("SwapTotal", 0),
        "swap_free": memory_values.get("SwapFree", 0),
    }
    try:
        stat = os.statvfs("/")
        filesystem = {
            "total": stat.f_frsize * stat.f_blocks,
            "free": stat.f_frsize * stat.f_bfree,
            "available": stat.f_frsize * stat.f_bavail,
        }
    except OSError:
        filesystem = {"total": 0, "free": 0, "available": 0}
    return {
        "uptime_seconds": max(0, uptime_seconds),
        "load_average": load_average,
        "memory_bytes": memory,
        "root_filesystem_bytes": filesystem,
        "origin_listener": {"port": ORIGIN_PORT, "listening": listener_present(ORIGIN_PORT)},
    }


def listener_present(port: int) -> bool:
    target = f"{port:04X}"
    for path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            columns = line.split()
            if len(columns) < 4:
                continue
            local = columns[1]
            state = columns[3]
            if ":" not in local:
                continue
            _, local_port = local.rsplit(":", 1)
            if local_port.upper() == target and state.upper() == "0A":
                return True
    return False


def collect_report(incident_at: str, window_minutes: int) -> tuple[dict[str, Any], int]:
    incident = parse_incident_at(incident_at)
    minutes = parse_window(window_minutes)
    start_dt = incident - dt.timedelta(minutes=minutes)
    end_dt = incident + dt.timedelta(minutes=minutes)
    start = iso_z(start_dt)
    end = iso_z(end_dt)

    docker_inventory_result = run_bounded(
        [
            "docker",
            "ps",
            "-a",
            "--no-trunc",
            "--format",
            '{{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}',
        ]
    )
    if docker_inventory_result["status"] in {"ok", "empty"}:
        inventory = parse_docker_inventory(docker_inventory_result["text"])
        docker_available = True
    else:
        inventory = {role: [] for role in SERVICE_ROLES}
        docker_available = False

    services = {role: service_summary(role, inventory[role], start, end) for role in SERVICE_ROLES}

    kernel_result = run_bounded(["journalctl", "-k", "--since", start, "--until", end, "--no-pager", "--output=cat"])
    system_result = run_bounded(
        [
            "journalctl",
            "-u",
            "docker.service",
            "-u",
            "cloudflared.service",
            "--since",
            start,
            "--until",
            end,
            "--no-pager",
            "--output=cat",
        ]
    )
    kernel_counts = count_signatures(kernel_result["text"])
    system_counts = count_signatures(system_result["text"])

    partial_reasons: list[str] = []
    if not docker_available:
        partial_reasons.append("docker_inventory_unavailable")
    for role, item in services.items():
        if item["ambiguous"]:
            partial_reasons.append(f"{role}_container_ambiguous")
        if item["present"] and item["inspect_status"] != "ok":
            partial_reasons.append(f"{role}_inspect_unavailable")
        if item["present"] and item["log_status"] not in {"ok", "empty"}:
            partial_reasons.append(f"{role}_logs_incomplete")
    if kernel_result["status"] not in {"ok", "empty"}:
        partial_reasons.append("kernel_journal_unavailable")
    if system_result["status"] not in {"ok", "empty"}:
        partial_reasons.append("system_journal_unavailable")
    partial_reasons = sorted(set(partial_reasons))

    report = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": iso_z(dt.datetime.now(dt.timezone.utc)),
        "incident_at": incident_at,
        "window": {"minutes": minutes, "start": start, "end": end},
        "collection_status": "partial" if partial_reasons else "complete",
        "partial_reasons": partial_reasons,
        "host": host_metrics(),
        "services": services,
        "kernel": {
            "status": kernel_result["status"],
            "truncated": bool(kernel_result["truncated"]),
            "oom_signature_count": kernel_counts["oom"],
        },
        "system_journal": {
            "status": system_result["status"],
            "truncated": bool(system_result["truncated"]),
            "signature_counts": system_counts,
        },
        "collection": {
            "docker_available": docker_available,
            "docker_inventory_status": docker_inventory_result["status"],
            "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
            "max_command_bytes": MAX_COMMAND_BYTES,
        },
    }
    return report, 2 if partial_reasons else 0


def write_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise CollectorError("output path already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(canonical.encode("utf-8")) > 1024 * 1024:
        raise CollectorError("report exceeds 1 MiB")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(canonical)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect sanitized Hermes Deals origin incident evidence")
    parser.add_argument("--incident-at", required=True)
    parser.add_argument("--window-minutes", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report, exit_code = collect_report(args.incident_at, parse_window(args.window_minutes))
        write_report(args.output, report)
    except CollectorError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
