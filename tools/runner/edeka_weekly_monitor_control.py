#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Mapping


CONTROL = "edeka-weekly-monitor-control"
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_BRIDGE_PR = 673
SERVICE_UNIT = "hermes-edeka-weekly-monitor.service"
TIMER_UNIT = "hermes-edeka-weekly-monitor.timer"
ALERT_UNIT = "hermes-edeka-weekly-monitor-failure@.service"
UNIT_NAMES = (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT)
UNIT_DIR = Path("/etc/systemd/system")
CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
EXPECTED_REPO_ROOT = str(SOURCE_REPO)
EXPECTED_PLANNER_BLOB = "749f4d2ff09d50a9d53e45887013d6d4d79ed69a"
EXPECTED_RUNTIME_BLOB = "4c863cf516a7de6cf8684b9b3ba3f1eb22785141"
EXPECTED_UNIT_REGISTRATION_INSTALLER_BLOB = "91ddc076ec6407b567a3ae3300bef0e8a7adfca5"
EXPECTED_SHADOW_EVIDENCE_ROOT = "/home/andris/hermes-deals-shadow-evidence/edeka"
EXPECTED_MONITOR_EVIDENCE_ROOT = "/home/andris/hermes-deals-edeka-weekly-monitor"
EXPECTED_CACHE_ROOT = "/home/andris/.cache/hermes-deals-edeka-shadow"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SPAN_RE = re.compile(r"[1-9][0-9]*(?:ms|s|min|h|d|w)")
CALENDAR_RE = re.compile(r"[A-Za-z0-9*:/.,~+_ -]{1,160}")
LIVE_ENABLE_STATES = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}


class ControlError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ControlError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_root_file(path: Path, mode: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and stat.S_IMODE(info.st_mode) == mode
    )


def run_command(argv: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"command failed: {Path(argv[0]).name} {' '.join(argv[1:])}")
    return result


def git(*args: str, check: bool = True, text: bool = False) -> subprocess.CompletedProcess[Any]:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(SOURCE_REPO), *args,
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=45,
        text=text,
    )
    if check:
        require(result.returncode == 0, f"audit Git command failed: {args[0]}")
        require(not result.stderr, f"audit Git command emitted stderr: {args[0]}")
    return result


def git_text(*args: str) -> str:
    return str(git(*args, text=True).stdout).strip()


def validate_exact_source_checkout(expected_sha: str) -> None:
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository is missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated EDEKA audit repository is not a Git checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == expected_sha, "dedicated EDEKA audit repository HEAD is not the registered SHA")
    git("show-ref", "--verify", "--quiet", "refs/remotes/origin/main")
    require(git_text("rev-parse", "refs/remotes/origin/main") == expected_sha, "dedicated EDEKA origin/main is not the registered SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated EDEKA audit repository is not clean")


def registration_core(config: Mapping[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in config if key != "registration_fingerprint_sha256"}


def validate_registration_config(config: Mapping[str, Any], expected_sha: str, expected_fingerprint: str) -> None:
    required = {
        "schema_version", "registration_sha", "repo_root", "planner_blob", "runtime_blob", "installer_blob",
        "schedule", "unit_sha256", "shadow_evidence_root", "monitor_evidence_root", "cache_root", "unit_dir",
        "registration_scope", "daemon_reload_performed", "timer_enable_performed", "timer_start_performed",
        "source_refetch_performed", "production_database_write_performed", "review_write_performed",
        "publication_write_performed", "production_deploy_performed", "registration_fingerprint_sha256",
    }
    require(set(config) == required, "unit registration config schema mismatch")
    require(config.get("schema_version") == 1, "unit registration schema mismatch")
    require(config.get("registration_sha") == expected_sha, "owner command registered SHA mismatch")
    require(config.get("repo_root") == EXPECTED_REPO_ROOT, "registered repo root mismatch")
    require(config.get("planner_blob") == EXPECTED_PLANNER_BLOB, "registered planner blob mismatch")
    require(config.get("runtime_blob") == EXPECTED_RUNTIME_BLOB, "registered runtime blob mismatch")
    require(config.get("installer_blob") == EXPECTED_UNIT_REGISTRATION_INSTALLER_BLOB, "registered unit installer blob mismatch")
    require(config.get("shadow_evidence_root") == EXPECTED_SHADOW_EVIDENCE_ROOT, "shadow evidence root mismatch")
    require(config.get("monitor_evidence_root") == EXPECTED_MONITOR_EVIDENCE_ROOT, "monitor evidence root mismatch")
    require(config.get("cache_root") == EXPECTED_CACHE_ROOT, "cache root mismatch")
    require(config.get("unit_dir") == str(UNIT_DIR), "unit directory mismatch")
    require(config.get("registration_scope") == "unit_files_only_no_manager_reload", "unit registration scope mismatch")
    for key in (
        "daemon_reload_performed", "timer_enable_performed", "timer_start_performed", "source_refetch_performed",
        "production_database_write_performed", "review_write_performed", "publication_write_performed",
        "production_deploy_performed",
    ):
        require(config.get(key) is False, f"unsafe registration history flag: {key}")

    schedule = config.get("schedule")
    require(isinstance(schedule, Mapping), "registration schedule missing")
    require(set(schedule) == {"on_calendar", "retry_delay", "retry_window", "max_attempts", "timeout_start", "runner_timeout_seconds"}, "registration schedule fields mismatch")
    on_calendar = schedule.get("on_calendar")
    require(isinstance(on_calendar, str) and "\n" not in on_calendar and "\r" not in on_calendar and CALENDAR_RE.fullmatch(on_calendar) is not None, "registered OnCalendar invalid")
    for key in ("retry_delay", "retry_window", "timeout_start"):
        value = schedule.get(key)
        require(isinstance(value, str) and SPAN_RE.fullmatch(value) is not None, f"registered {key} invalid")
    attempts = schedule.get("max_attempts")
    require(isinstance(attempts, int) and not isinstance(attempts, bool) and 2 <= attempts <= 5, "registered max_attempts invalid")
    timeout = schedule.get("runner_timeout_seconds")
    require(isinstance(timeout, int) and not isinstance(timeout, bool) and 60 <= timeout <= 7200, "registered runner timeout invalid")

    unit_sha = config.get("unit_sha256")
    require(isinstance(unit_sha, Mapping) and set(unit_sha) == set(UNIT_NAMES), "registered unit set mismatch")
    for name in UNIT_NAMES:
        require(SHA256_RE.fullmatch(str(unit_sha.get(name) or "")) is not None, f"registered unit SHA invalid: {name}")

    fingerprint = str(config.get("registration_fingerprint_sha256") or "")
    require(SHA256_RE.fullmatch(fingerprint) is not None, "registered fingerprint invalid")
    require(fingerprint == sha_bytes(canonical_bytes(registration_core(config))), "registered fingerprint drift")
    require(fingerprint == expected_fingerprint, "owner command registration fingerprint mismatch")


def load_registration(expected_sha: str, expected_fingerprint: str) -> dict[str, Any]:
    require(SHA40_RE.fullmatch(expected_sha) is not None, "expected registered SHA is invalid")
    require(SHA256_RE.fullmatch(expected_fingerprint) is not None, "expected registration fingerprint is invalid")
    require(regular_root_file(CONFIG, 0o600), "unit registration config missing or unsafe")
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError("unit registration config JSON invalid") from exc
    require(isinstance(config, dict), "unit registration config root invalid")
    validate_registration_config(config, expected_sha, expected_fingerprint)
    return config


def validate_installed_units(config: Mapping[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for name in UNIT_NAMES:
        path = UNIT_DIR / name
        require(regular_root_file(path, 0o644), f"installed EDEKA monitor unit missing or unsafe: {name}")
        require(sha_file(path) == config["unit_sha256"][name], f"installed EDEKA monitor unit SHA drift: {name}")
        result[name] = path
    return result


def preflight(config: Mapping[str, Any], units: Mapping[str, Path]) -> None:
    run_command(["/usr/bin/systemd-analyze", "calendar", str(config["schedule"]["on_calendar"])])
    run_command(["/usr/bin/systemd-analyze", "verify", *(str(units[name]) for name in UNIT_NAMES)])


def timer_enable_state() -> str:
    result = run_command(["/usr/bin/systemctl", "is-enabled", TIMER_UNIT], check=False)
    return result.stdout.strip()


def timer_is_live_enabled() -> bool:
    return timer_enable_state() in LIVE_ENABLE_STATES


def timer_is_active() -> bool:
    result = run_command(["/usr/bin/systemctl", "is-active", TIMER_UNIT], check=False)
    return result.stdout.strip() == "active"


def service_is_active() -> bool:
    result = run_command(["/usr/bin/systemctl", "is-active", SERVICE_UNIT], check=False)
    return result.stdout.strip() == "active"


def activate(config: Mapping[str, Any], expected_sha: str) -> dict[str, Any]:
    validate_exact_source_checkout(expected_sha)
    enabled_before = timer_is_live_enabled()
    active_before = timer_is_active()
    require(enabled_before == active_before, "timer enable/active state is inconsistent before activation")
    if enabled_before and active_before:
        return {
            "systemd_change_performed": False, "root_host_mutation_performed": False,
            "daemon_reload_performed": False, "timer_enable_performed": False, "timer_start_performed": False,
            "timer_disable_performed": False, "timer_stop_performed": False, "service_stop_performed": False,
            "timer_may_trigger_refetch": False, "activation_state": "already_active",
        }
    run_command(["/usr/bin/systemctl", "daemon-reload"])
    run_command(["/usr/bin/systemctl", "enable", "--no-reload", TIMER_UNIT])
    run_command(["/usr/bin/systemctl", "start", TIMER_UNIT])
    require(timer_is_live_enabled(), "timer did not become enabled")
    require(timer_is_active(), "timer did not become active")
    return {
        "systemd_change_performed": True, "root_host_mutation_performed": True,
        "daemon_reload_performed": True, "timer_enable_performed": True, "timer_start_performed": True,
        "timer_disable_performed": False, "timer_stop_performed": False, "service_stop_performed": False,
        "timer_may_trigger_refetch": True, "activation_state": "activated",
    }


def disable() -> dict[str, Any]:
    enabled_before = timer_is_live_enabled()
    timer_active_before = timer_is_active()
    service_active_before = service_is_active()
    run_command(["/usr/bin/systemctl", "stop", TIMER_UNIT], check=False)
    run_command(["/usr/bin/systemctl", "stop", SERVICE_UNIT], check=False)
    run_command(["/usr/bin/systemctl", "disable", "--no-reload", TIMER_UNIT], check=False)
    run_command(["/usr/bin/systemctl", "daemon-reload"])
    run_command(["/usr/bin/systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT], check=False)
    require(not timer_is_live_enabled(), "timer remains enabled after disable")
    require(not timer_is_active(), "timer remains active after disable")
    require(not service_is_active(), "service remains active after disable")
    changed = enabled_before or timer_active_before or service_active_before
    return {
        "systemd_change_performed": changed, "root_host_mutation_performed": enabled_before,
        "daemon_reload_performed": True, "timer_enable_performed": False, "timer_start_performed": False,
        "timer_disable_performed": enabled_before, "timer_stop_performed": timer_active_before,
        "service_stop_performed": service_active_before, "timer_may_trigger_refetch": False,
        "activation_state": "disabled",
    }


def _unlink_verified(path: Path, *, mode: int, expected_sha256: str | None = None) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    require(regular_root_file(path, mode), f"rollback path metadata drift: {path}")
    if expected_sha256 is not None:
        require(sha_file(path) == expected_sha256, f"rollback path content drift: {path}")
    path.unlink()
    parent_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return True


def rollback(config: Mapping[str, Any]) -> dict[str, Any]:
    disabled = disable()
    removed = 0
    for name in UNIT_NAMES:
        if _unlink_verified(UNIT_DIR / name, mode=0o644, expected_sha256=str(config["unit_sha256"][name])):
            removed += 1
    config_removed = _unlink_verified(CONFIG, mode=0o600)
    run_command(["/usr/bin/systemctl", "daemon-reload"])
    run_command(["/usr/bin/systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT], check=False)
    require(not timer_is_live_enabled() and not timer_is_active() and not service_is_active(), "monitor remains live after rollback")
    for name in UNIT_NAMES:
        require(not (UNIT_DIR / name).exists() and not (UNIT_DIR / name).is_symlink(), f"unit remains after rollback: {name}")
    require(not CONFIG.exists() and not CONFIG.is_symlink(), "registration config remains after rollback")
    return {
        **disabled,
        "systemd_change_performed": True,
        "root_host_mutation_performed": bool(removed or config_removed or disabled["root_host_mutation_performed"]),
        "daemon_reload_performed": True,
        "removed_unit_count": removed,
        "registration_config_removed": config_removed,
        "activation_state": "rolled_back",
    }


def parse_argv(argv: list[str]) -> tuple[str, str, str, bool, bool]:
    if not argv:
        raise ControlError("operation is required")
    operation = argv[0]
    require(operation in {"activate", "disable", "rollback"}, "unsupported EDEKA monitor operation")
    if operation == "activate":
        require(len(argv) == 5, "activate requires exact registered SHA, fingerprint, refetch and retry authority")
        require(argv[3] == "source-refetch-authorized", "activate source-refetch authority token missing")
        require(argv[4] == "bounded-retries-authorized", "activate bounded-retry authority token missing")
        return operation, argv[1], argv[2], True, True
    require(len(argv) == 3, f"{operation} requires exact registered SHA and fingerprint")
    return operation, argv[1], argv[2], False, False


def execute(argv: list[str]) -> dict[str, Any]:
    require(os.geteuid() == 0, "EDEKA monitor control must run as root")
    operation, expected_sha, expected_fingerprint, refetch_authorized, retry_authorized = parse_argv(argv)
    require(SHA40_RE.fullmatch(expected_sha) is not None, "expected registered SHA is invalid")
    require(SHA256_RE.fullmatch(expected_fingerprint) is not None, "expected registration fingerprint is invalid")
    config = load_registration(expected_sha, expected_fingerprint)
    units = validate_installed_units(config)
    preflight(config, units)
    if operation == "activate":
        detail = activate(config, expected_sha)
    elif operation == "disable":
        detail = disable()
    else:
        detail = rollback(config)
    return {
        "schema_version": 1, "control": CONTROL, "issue_number": EXPECTED_ISSUE_NUMBER,
        "bridge_pr": EXPECTED_BRIDGE_PR, "operation": operation, "result": "PASS",
        "registered_commit": expected_sha, "registration_fingerprint": expected_fingerprint,
        "source_refetch_authorized": refetch_authorized, "bounded_retry_authorized": retry_authorized,
        "source_refetch_performed_by_control": False,
        "rollback_preserves_shadow_evidence_root": True,
        "rollback_preserves_monitor_evidence_root": True,
        "rollback_preserves_cache_root": True,
        "production_database_write_authorized": False, "review_write_authorized": False,
        "publication_write_authorized": False, "deployment_authorized": False,
        **detail,
    }


def main(argv: list[str] | None = None) -> int:
    import sys
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        result = execute(values)
    except (OSError, UnicodeError, ValueError, ControlError, subprocess.SubprocessError) as exc:
        print(json.dumps({"schema_version": 1, "control": CONTROL, "result": "BLOCKED", "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
