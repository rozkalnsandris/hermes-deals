#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Mapping

CONTROL = "edeka-weekly-monitor-control-v1"
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_REGISTRATION_SHA = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
EXPECTED_REGISTRATION_FINGERPRINT = "f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb"
EXPECTED_PLANNER_BLOB = "749f4d2ff09d50a9d53e45887013d6d4d79ed69a"
EXPECTED_RUNTIME_BLOB = "4c863cf516a7de6cf8684b9b3ba3f1eb22785141"
EXPECTED_INSTALLER_BLOB = "91ddc076ec6407b567a3ae3300bef0e8a7adfca5"
EXPECTED_UNIT_SHA256 = {
    "hermes-edeka-weekly-monitor.service": "d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de",
    "hermes-edeka-weekly-monitor.timer": "8f177a8752b9bc9684a87ad3f2f1cd5c367a915591ca6f66d31b0ff8189f34b8",
    "hermes-edeka-weekly-monitor-failure@.service": "c5faf2255c86d8908230449315e5a8b1813b61ae300d4c32899ada9e38c1e9b7",
}
EXPECTED_SCHEDULE = {
    "on_calendar": "Mon *-*-* 06:15:00 Europe/Berlin",
    "retry_delay": "30min",
    "retry_window": "6h",
    "max_attempts": 3,
    "timeout_start": "50min",
    "runner_timeout_seconds": 2700,
}
SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
SERVICE_UNIT = "hermes-edeka-weekly-monitor.service"
TIMER_UNIT = "hermes-edeka-weekly-monitor.timer"
ALERT_UNIT = "hermes-edeka-weekly-monitor-failure@.service"
UNIT_NAMES = (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT)
UNIT_DIR = Path("/etc/systemd/system")
REGISTRATION_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
CONTROL_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-control.json")
SHADOW_EVIDENCE_ROOT = Path("/home/andris/hermes-deals-shadow-evidence/edeka")
MONITOR_EVIDENCE_ROOT = Path("/home/andris/hermes-deals-edeka-weekly-monitor")
CACHE_ROOT = Path("/home/andris/.cache/hermes-deals-edeka-shadow")
RUNTIME_REL = "tools/edeka_weekly_monitor_runtime.py"
PLANNER_REL = "tools/edeka_weekly_monitor_activation_plan.py"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
OPERATIONS = {"activate", "disable", "rollback"}


class ControlError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ControlError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
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


def load_json_root_file(path: Path, mode: int, label: str) -> dict[str, Any]:
    require(regular_root_file(path, mode), f"{label} missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError(f"{label} JSON invalid") from exc
    require(isinstance(value, dict), f"{label} root invalid")
    return value


def run(argv: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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
        require(result.returncode == 0, f"command failed: {Path(argv[0]).name}")
    return result


def git(*args: str, check: bool = True, text: bool = True) -> subprocess.CompletedProcess[str]:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(SOURCE_REPO), *args,
    ]
    result = run(command, check=False, timeout=45)
    if check:
        require(result.returncode == 0, f"audit Git command failed: {args[0]}")
        require(not result.stderr, f"audit Git command emitted stderr: {args[0]}")
    return result


def git_text(*args: str) -> str:
    return git(*args).stdout.strip()


def validate_registration_config(expected_fingerprint: str) -> dict[str, Any]:
    config = load_json_root_file(REGISTRATION_CONFIG, 0o600, "EDEKA monitor registration config")
    expected_keys = {
        "schema_version",
        "registration_sha",
        "repo_root",
        "planner_blob",
        "runtime_blob",
        "installer_blob",
        "schedule",
        "unit_sha256",
        "shadow_evidence_root",
        "monitor_evidence_root",
        "cache_root",
        "unit_dir",
        "registration_scope",
        "daemon_reload_performed",
        "timer_enable_performed",
        "timer_start_performed",
        "source_refetch_performed",
        "production_database_write_performed",
        "review_write_performed",
        "publication_write_performed",
        "production_deploy_performed",
        "registration_fingerprint_sha256",
    }
    require(set(config) == expected_keys, "registration config schema drift")
    require(config.get("schema_version") == 1, "registration schema mismatch")
    require(config.get("registration_sha") == EXPECTED_REGISTRATION_SHA, "registration SHA drift")
    require(config.get("repo_root") == str(SOURCE_REPO), "registration repo root drift")
    require(config.get("planner_blob") == EXPECTED_PLANNER_BLOB, "registration planner blob drift")
    require(config.get("runtime_blob") == EXPECTED_RUNTIME_BLOB, "registration runtime blob drift")
    require(config.get("installer_blob") == EXPECTED_INSTALLER_BLOB, "registration installer blob drift")
    require(config.get("schedule") == EXPECTED_SCHEDULE, "registration schedule drift")
    require(config.get("unit_sha256") == EXPECTED_UNIT_SHA256, "registration unit hash drift")
    require(config.get("shadow_evidence_root") == str(SHADOW_EVIDENCE_ROOT), "shadow evidence root drift")
    require(config.get("monitor_evidence_root") == str(MONITOR_EVIDENCE_ROOT), "monitor evidence root drift")
    require(config.get("cache_root") == str(CACHE_ROOT), "cache root drift")
    require(config.get("unit_dir") == str(UNIT_DIR), "unit directory drift")
    require(config.get("registration_scope") == "unit_files_only_no_manager_reload", "registration scope drift")
    for key in (
        "daemon_reload_performed",
        "timer_enable_performed",
        "timer_start_performed",
        "source_refetch_performed",
        "production_database_write_performed",
        "review_write_performed",
        "publication_write_performed",
        "production_deploy_performed",
    ):
        require(config.get(key) is False, f"unsafe registration flag: {key}")

    core = {key: value for key, value in config.items() if key != "registration_fingerprint_sha256"}
    computed = sha256_bytes(canonical_bytes(core))
    require(computed == EXPECTED_REGISTRATION_FINGERPRINT, "registration fingerprint recomputation mismatch")
    require(config.get("registration_fingerprint_sha256") == computed, "stored registration fingerprint drift")
    require(expected_fingerprint == computed, "owner command registration fingerprint mismatch")
    return config


def validate_control_config(control_sha: str, expected_fingerprint: str) -> dict[str, Any]:
    config = load_json_root_file(CONTROL_CONFIG, 0o600, "EDEKA monitor control config")
    expected_keys = {
        "schema_version",
        "control",
        "issue_number",
        "control_sha",
        "dispatcher_blob",
        "dispatcher_sha256",
        "registration_sha",
        "registration_fingerprint_sha256",
        "root_registration_only",
        "systemd_change_performed",
        "source_refetch_performed",
        "production_database_write_performed",
        "review_write_performed",
        "publication_write_performed",
        "production_deploy_performed",
    }
    require(set(config) == expected_keys, "control config schema drift")
    require(config.get("schema_version") == 1 and config.get("control") == CONTROL, "control config identity drift")
    require(config.get("issue_number") == EXPECTED_ISSUE_NUMBER, "control issue drift")
    require(config.get("control_sha") == control_sha and SHA40_RE.fullmatch(control_sha) is not None, "control SHA mismatch")
    require(config.get("registration_sha") == EXPECTED_REGISTRATION_SHA, "control registration SHA drift")
    require(config.get("registration_fingerprint_sha256") == expected_fingerprint, "control fingerprint drift")
    require(config.get("root_registration_only") is True, "control root-registration gate drift")
    for key in (
        "systemd_change_performed",
        "source_refetch_performed",
        "production_database_write_performed",
        "review_write_performed",
        "publication_write_performed",
        "production_deploy_performed",
    ):
        require(config.get(key) is False, f"unsafe control registration flag: {key}")
    dispatcher_blob = str(config.get("dispatcher_blob") or "")
    require(SHA40_RE.fullmatch(dispatcher_blob) is not None, "control dispatcher Git blob invalid")
    dispatcher_sha = str(config.get("dispatcher_sha256") or "")
    require(SHA256_RE.fullmatch(dispatcher_sha) is not None, "control dispatcher SHA256 invalid")
    require(sha256_file(Path(__file__).resolve()) == dispatcher_sha, "running control dispatcher bytes drift")
    return config


def validate_installed_units(registration: Mapping[str, Any]) -> None:
    for name in UNIT_NAMES:
        path = UNIT_DIR / name
        require(regular_root_file(path, 0o644), f"installed unit missing or unsafe: {name}")
        require(sha256_file(path) == registration["unit_sha256"][name], f"installed unit SHA drift: {name}")


def validate_runtime_checkout(registration: Mapping[str, Any]) -> None:
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated EDEKA audit repository is not a Git checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == EXPECTED_REGISTRATION_SHA, "dedicated EDEKA audit HEAD drifted from registration SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == "", "dedicated EDEKA audit repository is not clean")
    require(git_text("rev-parse", f"HEAD:{RUNTIME_REL}") == registration["runtime_blob"], "runtime Git blob drift")
    require(git_text("rev-parse", f"HEAD:{PLANNER_REL}") == registration["planner_blob"], "planner Git blob drift")
    require(git_text("hash-object", str(SOURCE_REPO / RUNTIME_REL)) == registration["runtime_blob"], "runtime working-tree bytes drift")


def systemctl_state(verb: str, unit: str) -> tuple[int, str]:
    result = run(["/usr/bin/systemctl", verb, unit], check=False)
    return result.returncode, result.stdout.strip()


def timer_enabled() -> bool:
    _, state = systemctl_state("is-enabled", TIMER_UNIT)
    return state == "enabled"


def unit_active(unit: str) -> bool:
    rc, state = systemctl_state("is-active", unit)
    return rc == 0 and state == "active"


def verify_disabled_inactive() -> None:
    require(not timer_enabled(), "timer remains enabled")
    require(not unit_active(TIMER_UNIT), "timer remains active")
    require(not unit_active(SERVICE_UNIT), "monitor service remains active")


def preflight_units(registration: Mapping[str, Any]) -> None:
    validate_installed_units(registration)
    run(["/usr/bin/systemd-analyze", "calendar", EXPECTED_SCHEDULE["on_calendar"]])
    run(["/usr/bin/systemd-analyze", "verify", *(str(UNIT_DIR / name) for name in UNIT_NAMES)])


def fail_safe_disable() -> bool:
    run(["/usr/bin/systemctl", "stop", TIMER_UNIT], check=False)
    run(["/usr/bin/systemctl", "--no-reload", "disable", TIMER_UNIT], check=False)
    run(["/usr/bin/systemctl", "stop", SERVICE_UNIT], check=False)
    run(["/usr/bin/systemctl", "daemon-reload"], check=False)
    run(["/usr/bin/systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT], check=False)
    try:
        verify_disabled_inactive()
    except ControlError:
        return False
    return True


def activate(registration: Mapping[str, Any]) -> dict[str, Any]:
    validate_runtime_checkout(registration)
    preflight_units(registration)
    require(not timer_enabled(), "timer already enabled before activation")
    require(not unit_active(TIMER_UNIT), "timer already active before activation")
    require(not unit_active(SERVICE_UNIT), "monitor service unexpectedly active before activation")
    try:
        run(["/usr/bin/systemctl", "daemon-reload"])
        run(["/usr/bin/systemctl", "--no-reload", "enable", TIMER_UNIT])
        run(["/usr/bin/systemctl", "start", TIMER_UNIT])
        require(timer_enabled(), "timer did not become enabled")
        require(unit_active(TIMER_UNIT), "timer did not become active")
    except Exception:
        cleanup_ok = fail_safe_disable()
        if not cleanup_ok:
            raise ControlError("activation failed and fail-safe cleanup could not be verified")
        raise
    return {
        "timer_enabled": True,
        "timer_active": True,
        "service_active_after_activation": unit_active(SERVICE_UNIT),
        "source_refetch_authorized": True,
        "bounded_retry_authorized": True,
        "source_refetch_may_have_been_triggered": True,
        "fail_safe_cleanup_required": False,
    }


def disable(registration: Mapping[str, Any]) -> dict[str, Any]:
    preflight_units(registration)
    cleanup_ok = fail_safe_disable()
    require(cleanup_ok, "disable could not verify safe inactive state")
    validate_installed_units(registration)
    return {
        "timer_enabled": False,
        "timer_active": False,
        "service_active_after_disable": False,
        "installed_unit_count": len(UNIT_NAMES),
        "source_refetch_authorized": False,
        "bounded_retry_authorized": False,
        "source_refetch_may_have_been_triggered": False,
    }


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def rollback(control_sha: str, expected_fingerprint: str) -> dict[str, Any]:
    registration = validate_registration_config(expected_fingerprint)
    preflight_units(registration)
    cleanup_ok = fail_safe_disable()
    require(cleanup_ok, "rollback could not verify safe inactive state")

    registration = validate_registration_config(expected_fingerprint)
    validate_control_config(control_sha, expected_fingerprint)
    validate_installed_units(registration)

    removed = 0
    for name in UNIT_NAMES:
        path = UNIT_DIR / name
        require(regular_root_file(path, 0o644), f"rollback unit metadata drift: {name}")
        require(sha256_file(path) == EXPECTED_UNIT_SHA256[name], f"rollback unit content drift: {name}")
        path.unlink()
        removed += 1
    fsync_directory(UNIT_DIR)

    run(["/usr/bin/systemctl", "daemon-reload"])
    run(["/usr/bin/systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT], check=False)
    verify_disabled_inactive()
    for name in UNIT_NAMES:
        path = UNIT_DIR / name
        require(not path.exists() and not path.is_symlink(), f"unit remains after rollback: {name}")
    return {
        "timer_enabled": False,
        "timer_active": False,
        "service_active_after_rollback": False,
        "removed_unit_count": removed,
        "source_refetch_authorized": False,
        "bounded_retry_authorized": False,
        "source_refetch_may_have_been_triggered": False,
    }


def execute(
    operation: str,
    control_sha: str,
    expected_fingerprint: str,
    refetch_authority: str,
    retry_authority: str,
) -> dict[str, Any]:
    require(os.geteuid() == 0, "EDEKA monitor control must run as root")
    require(operation in OPERATIONS, "unsupported EDEKA monitor operation")
    require(SHA40_RE.fullmatch(control_sha) is not None, "control SHA is invalid")
    require(expected_fingerprint == EXPECTED_REGISTRATION_FINGERPRINT, "registration fingerprint mismatch")
    validate_control_config(control_sha, expected_fingerprint)
    registration = validate_registration_config(expected_fingerprint)

    if operation == "activate":
        require(refetch_authority == "source-refetch=authorized", "activate source-refetch authority missing")
        require(retry_authority == "bounded-retries=authorized", "activate bounded-retry authority missing")
        detail = activate(registration)
    elif operation == "disable":
        require(refetch_authority == "source-refetch=forbidden", "disable must forbid source refetch")
        require(retry_authority == "bounded-retries=forbidden", "disable must forbid bounded retries")
        detail = disable(registration)
    else:
        require(refetch_authority == "source-refetch=forbidden", "rollback must forbid source refetch")
        require(retry_authority == "bounded-retries=forbidden", "rollback must forbid bounded retries")
        detail = rollback(control_sha, expected_fingerprint)

    return {
        "schema_version": 1,
        "control": CONTROL,
        "issue_number": EXPECTED_ISSUE_NUMBER,
        "operation": operation,
        "result": "PASS",
        "control_sha": control_sha,
        "registered_commit": EXPECTED_REGISTRATION_SHA,
        "registration_fingerprint_sha256": EXPECTED_REGISTRATION_FINGERPRINT,
        "systemd_change_performed": True,
        "rollback_preserves_shadow_evidence_root": True,
        "rollback_preserves_monitor_evidence_root": True,
        "rollback_preserves_cache_root": True,
        "production_database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
        **detail,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply one owner-authorized EDEKA weekly monitor control operation.")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("control_sha")
    parser.add_argument("registration_fingerprint")
    parser.add_argument("refetch_authority")
    parser.add_argument("retry_authority")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = execute(
            args.operation,
            args.control_sha,
            args.registration_fingerprint,
            args.refetch_authority,
            args.retry_authority,
        )
    except (OSError, ValueError, ControlError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "control": CONTROL,
                    "result": "BLOCKED",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
