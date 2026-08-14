#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping

CONTROL = "lidl-gate-d-control"
EXPECTED_ISSUE_NUMBER = 24
EXPECTED_BRIDGE_PR = 656
SERVICE_UNIT = "hermes-lidl-weekly.service"
TIMER_UNIT = "hermes-lidl-weekly.timer"
ALERT_UNIT = "hermes-lidl-weekly-failure@.service"
UNIT_NAMES = (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT)
CONFIG = Path("/etc/hermes-deals-audits.d/lidl-gate-d-control.json")
UNIT_DIR = Path("/etc/systemd/system")
CONTROL_ROOT = Path("/usr/local/libexec/hermes-deals-lidl-gate-d-control")
EXPECTED_REPO_ROOT = "/home/andris/hermes-deals-audit-source-lidl"
EXPECTED_PYTHON_PATH = "/usr/bin/python3"
EXPECTED_CORPUS_ROOT = "/home/andris/hermes-deals-lidl-corpus"
EXPECTED_EVIDENCE_ROOT = "/home/andris/hermes-deals-lidl-weekly-evidence"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SPAN_RE = re.compile(r"[1-9][0-9]*(?:ms|s|min|h|d|w)")
CALENDAR_RE = re.compile(r"[A-Za-z0-9*:/.,~+_ -]{1,160}")
PATH_RE = re.compile(r"/[A-Za-z0-9._/@-]+")
OPERATIONS = {"activate", "disable", "rollback"}
FALSE_FLAGS = (
    "production_write_authorized",
    "database_write_authorized",
    "review_write_authorized",
    "publication_authorized",
    "deployment_authorized",
)


class ControlError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ControlError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


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


def safe_absolute(value: Any, label: str) -> str:
    require(isinstance(value, str) and PATH_RE.fullmatch(value) is not None, f"{label} path is invalid")
    path = Path(value)
    require(path.is_absolute(), f"{label} must be absolute")
    require("//" not in value and "/../" not in f"{value}/" and "/./" not in f"{value}/", f"{label} is not normalized")
    return value


def plan_payload(config: Mapping[str, Any]) -> dict[str, Any]:
    schedule = config.get("schedule")
    units = config.get("units")
    require(isinstance(schedule, Mapping), "schedule config is missing")
    require(isinstance(units, Mapping), "unit config is missing")
    return {
        "schema_version": 1,
        "registration_sha": config.get("registration_sha"),
        "target": config.get("target"),
        "repo_root": config.get("repo_root"),
        "python_path": config.get("python_path"),
        "corpus_root": config.get("corpus_root"),
        "evidence_root": config.get("evidence_root"),
        "schedule": {
            "on_calendar": schedule.get("on_calendar"),
            "retry_delay": schedule.get("retry_delay"),
            "retry_window": schedule.get("retry_window"),
            "max_attempts": schedule.get("max_attempts"),
            "timeout_start": schedule.get("timeout_start"),
        },
        "unit_sha256": {name: units.get(name, {}).get("sha256") if isinstance(units.get(name), Mapping) else None for name in UNIT_NAMES},
    }


def plan_fingerprint(config: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(plan_payload(config))).hexdigest()


def validate_config_data(config: Mapping[str, Any], expected_plan: str) -> None:
    required = {
        "schema_version",
        "control",
        "issue_number",
        "bridge_pr",
        "registration_sha",
        "plan_fingerprint",
        "repo_root",
        "python_path",
        "corpus_root",
        "evidence_root",
        "target",
        "schedule",
        "units",
        "activation_requires_explicit_owner_authorization",
        "root_registration_only",
        *FALSE_FLAGS,
    }
    require(set(config) == required, "control config schema mismatch")
    require(config.get("schema_version") == 1 and config.get("control") == CONTROL, "control config identity mismatch")
    require(config.get("issue_number") == EXPECTED_ISSUE_NUMBER, "control issue mismatch")
    require(config.get("bridge_pr") == EXPECTED_BRIDGE_PR, "control PR mismatch")
    registration_sha = str(config.get("registration_sha") or "")
    require(SHA40_RE.fullmatch(registration_sha) is not None, "registration SHA is invalid")
    require(config.get("target") == "current", "unattended Gate D target must be current")
    expected_paths = {
        "repo_root": EXPECTED_REPO_ROOT,
        "python_path": EXPECTED_PYTHON_PATH,
        "corpus_root": EXPECTED_CORPUS_ROOT,
        "evidence_root": EXPECTED_EVIDENCE_ROOT,
    }
    for key, expected in expected_paths.items():
        safe_absolute(config.get(key), key)
        require(config.get(key) == expected, f"{key} is not the reviewed Gate D path")
    require(config.get("activation_requires_explicit_owner_authorization") is True, "owner activation gate missing")
    require(config.get("root_registration_only") is True, "root registration gate missing")
    for key in FALSE_FLAGS:
        require(config.get(key) is False, f"unsafe authority flag: {key}")

    schedule = config.get("schedule")
    require(isinstance(schedule, Mapping), "schedule config is missing")
    require(set(schedule) == {"on_calendar", "retry_delay", "retry_window", "max_attempts", "timeout_start"}, "schedule fields mismatch")
    on_calendar = schedule.get("on_calendar")
    require(isinstance(on_calendar, str) and "\n" not in on_calendar and "\r" not in on_calendar and CALENDAR_RE.fullmatch(on_calendar) is not None, "OnCalendar is invalid")
    for key in ("retry_delay", "retry_window", "timeout_start"):
        value = schedule.get(key)
        require(isinstance(value, str) and SPAN_RE.fullmatch(value) is not None, f"{key} is invalid")
    attempts = schedule.get("max_attempts")
    require(isinstance(attempts, int) and not isinstance(attempts, bool) and 2 <= attempts <= 5, "max_attempts is invalid")

    units = config.get("units")
    require(isinstance(units, Mapping) and set(units) == set(UNIT_NAMES), "unit set mismatch")
    for name in UNIT_NAMES:
        row = units.get(name)
        require(isinstance(row, Mapping) and set(row) == {"path", "sha256"}, f"unit config mismatch: {name}")
        path = safe_absolute(row.get("path"), f"staged {name}")
        require(Path(path) == CONTROL_ROOT / registration_sha / name, f"staged unit path mismatch: {name}")
        require(SHA256_RE.fullmatch(str(row.get("sha256") or "")) is not None, f"unit SHA invalid: {name}")

    configured_plan = str(config.get("plan_fingerprint") or "")
    require(SHA256_RE.fullmatch(configured_plan) is not None, "configured plan fingerprint is invalid")
    require(configured_plan == plan_fingerprint(config), "configured plan fingerprint drift")
    require(expected_plan == configured_plan, "owner command plan fingerprint mismatch")


def load_config(expected_plan: str) -> dict[str, Any]:
    require(regular_root_file(CONFIG, 0o600), "control config missing or unsafe")
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ControlError("control config JSON invalid") from exc
    require(isinstance(config, dict), "control config root invalid")
    validate_config_data(config, expected_plan)
    return config


def validate_staged_units(config: Mapping[str, Any]) -> dict[str, Path]:
    units = config["units"]
    result: dict[str, Path] = {}
    common_parent: Path | None = None
    for name in UNIT_NAMES:
        row = units[name]
        path = Path(str(row["path"]))
        require(regular_root_file(path, 0o444), f"staged unit missing or unsafe: {name}")
        require(sha_file(path) == row["sha256"], f"staged unit SHA drift: {name}")
        parent = path.parent.resolve(strict=True)
        if common_parent is None:
            common_parent = parent
        require(parent == common_parent, "staged units do not share one immutable registration directory")
        result[name] = path
    return result


def run_command(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=90,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"command failed: {Path(argv[0]).name} {' '.join(argv[1:])}")
    return result


def preflight(config: Mapping[str, Any], staged: Mapping[str, Path]) -> None:
    run_command(["/usr/bin/systemd-analyze", "calendar", str(config["schedule"]["on_calendar"])])
    run_command(["/usr/bin/systemd-analyze", "verify", *(str(staged[name]) for name in UNIT_NAMES)])


def installed_state(config: Mapping[str, Any]) -> dict[str, bool]:
    present: dict[str, bool] = {}
    for name in UNIT_NAMES:
        path = UNIT_DIR / name
        if not path.exists() and not path.is_symlink():
            present[name] = False
            continue
        require(regular_root_file(path, 0o644), f"installed unit metadata drift: {name}")
        require(sha_file(path) == config["units"][name]["sha256"], f"installed unit content drift: {name}")
        present[name] = True
    return present


def install_exclusive(src: Path, dst: Path) -> None:
    require(UNIT_DIR.is_dir() and not UNIT_DIR.is_symlink(), "systemd unit directory is missing or unsafe")
    info = UNIT_DIR.stat()
    require(info.st_uid == 0 and info.st_gid == 0, "systemd unit directory owner mismatch")
    fd, temp_name = tempfile.mkstemp(prefix=f".{dst.name}.lidl-gate-d-", dir=UNIT_DIR)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle, src.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o644)
        os.close(fd)
        fd = -1
        os.link(temp, dst, follow_symlinks=False)
        dir_fd = os.open(UNIT_DIR, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)


def ensure_evidence_root(path: Path) -> bool:
    require(path == Path("/home/andris/hermes-deals-lidl-weekly-evidence"), "evidence root path is not the reviewed Gate D path")
    try:
        owner = pwd.getpwnam("andris")
        group = grp.getgrnam("andris")
    except KeyError as exc:
        raise ControlError("andris account is unavailable") from exc
    if path.exists() or path.is_symlink():
        require(path.is_dir() and not path.is_symlink(), "evidence root is unsafe")
        info = path.stat()
        require(info.st_uid == owner.pw_uid and info.st_gid == group.gr_gid, "evidence root owner mismatch")
        require(stat.S_IMODE(info.st_mode) == 0o700, "evidence root mode mismatch")
        return False
    path.mkdir(mode=0o700)
    os.chown(path, owner.pw_uid, group.gr_gid)
    os.chmod(path, 0o700)
    return True


def timer_is_enabled() -> bool:
    result = run_command(["/usr/bin/systemctl", "is-enabled", TIMER_UNIT], check=False)
    return result.stdout.strip() == "enabled"


def timer_is_active() -> bool:
    result = run_command(["/usr/bin/systemctl", "is-active", TIMER_UNIT], check=False)
    return result.stdout.strip() == "active"


def disable_units() -> None:
    run_command(["/usr/bin/systemctl", "disable", "--now", TIMER_UNIT], check=False)
    run_command(["/usr/bin/systemctl", "stop", SERVICE_UNIT], check=False)
    run_command(["/usr/bin/systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT], check=False)
    require(not timer_is_enabled(), "timer remains enabled after disable")
    require(not timer_is_active(), "timer remains active after disable")


def activate(config: Mapping[str, Any], staged: Mapping[str, Path]) -> dict[str, Any]:
    existing = installed_state(config)
    created: list[Path] = []
    evidence_created = False
    try:
        evidence_created = ensure_evidence_root(Path(str(config["evidence_root"])))
        for name in UNIT_NAMES:
            if existing[name]:
                continue
            dst = UNIT_DIR / name
            install_exclusive(staged[name], dst)
            require(regular_root_file(dst, 0o644), f"installed unit metadata invalid: {name}")
            require(sha_file(dst) == config["units"][name]["sha256"], f"installed unit SHA invalid: {name}")
            created.append(dst)
        run_command(["/usr/bin/systemctl", "daemon-reload"])
        run_command(["/usr/bin/systemctl", "enable", "--now", TIMER_UNIT])
        require(timer_is_enabled(), "timer did not become enabled")
        require(timer_is_active(), "timer did not become active")
    except Exception:
        try:
            disable_units()
        except Exception:
            pass
        for path in reversed(created):
            try:
                name = path.name
                if regular_root_file(path, 0o644) and sha_file(path) == config["units"][name]["sha256"]:
                    path.unlink()
            except Exception:
                pass
        try:
            run_command(["/usr/bin/systemctl", "daemon-reload"], check=False)
        except Exception:
            pass
        raise
    return {"installed_unit_count": sum(1 for value in existing.values() if value) + len(created), "evidence_root_created": evidence_created}


def disable(config: Mapping[str, Any]) -> dict[str, Any]:
    installed_state(config)
    disable_units()
    return {"installed_unit_count": sum(installed_state(config).values()), "evidence_root_created": False}


def rollback(config: Mapping[str, Any]) -> dict[str, Any]:
    installed_state(config)
    disable_units()
    removed = 0
    for name in UNIT_NAMES:
        path = UNIT_DIR / name
        if not path.exists() and not path.is_symlink():
            continue
        require(regular_root_file(path, 0o644), f"rollback unit metadata drift: {name}")
        require(sha_file(path) == config["units"][name]["sha256"], f"rollback unit content drift: {name}")
        path.unlink()
        removed += 1
    run_command(["/usr/bin/systemctl", "daemon-reload"])
    run_command(["/usr/bin/systemctl", "reset-failed", SERVICE_UNIT, TIMER_UNIT], check=False)
    require(not timer_is_enabled() and not timer_is_active(), "timer remains live after rollback")
    for name in UNIT_NAMES:
        require(not (UNIT_DIR / name).exists() and not (UNIT_DIR / name).is_symlink(), f"unit remains after rollback: {name}")
    return {"removed_unit_count": removed, "installed_unit_count": 0, "evidence_root_created": False}


def execute(operation: str, expected_plan: str) -> dict[str, Any]:
    require(os.geteuid() == 0, "Lidl Gate D control must run as root")
    require(operation in OPERATIONS, "unsupported Gate D operation")
    require(SHA256_RE.fullmatch(expected_plan) is not None, "expected plan fingerprint is invalid")
    config = load_config(expected_plan)
    staged = validate_staged_units(config)
    preflight(config, staged)
    if operation == "activate":
        detail = activate(config, staged)
    elif operation == "disable":
        detail = disable(config)
    else:
        detail = rollback(config)
    receipt = {
        "schema_version": 1,
        "control": CONTROL,
        "issue_number": EXPECTED_ISSUE_NUMBER,
        "bridge_pr": EXPECTED_BRIDGE_PR,
        "operation": operation,
        "result": "PASS",
        "registered_commit": config["registration_sha"],
        "plan_fingerprint": config["plan_fingerprint"],
        "systemd_change_performed": True,
        "rollback_preserves_evidence_root": True,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
        **detail,
    }
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply one owner-authorized Lidl Gate D systemd control operation.")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("plan_fingerprint")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = execute(args.operation, args.plan_fingerprint)
    except (OSError, ValueError, ControlError, subprocess.SubprocessError) as exc:
        print(json.dumps({"schema_version": 1, "control": CONTROL, "result": "BLOCKED", "error_type": type(exc).__name__}, sort_keys=True))
        return 30
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
