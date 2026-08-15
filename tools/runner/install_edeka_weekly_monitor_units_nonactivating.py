#!/usr/bin/env python3
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping


SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
INSTALLER_REL = "tools/runner/install_edeka_weekly_monitor_units_nonactivating.py"
PLANNER_REL = "tools/edeka_weekly_monitor_activation_plan.py"
RUNTIME_REL = "tools/edeka_weekly_monitor_runtime.py"
EXPECTED_PLANNER_BLOB = "749f4d2ff09d50a9d53e45887013d6d4d79ed69a"
EXPECTED_RUNTIME_BLOB = "4c863cf516a7de6cf8684b9b3ba3f1eb22785141"
SERVICE_UNIT = "hermes-edeka-weekly-monitor.service"
TIMER_UNIT = "hermes-edeka-weekly-monitor.timer"
ALERT_UNIT = "hermes-edeka-weekly-monitor-failure@.service"
UNIT_NAMES = (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT)
UNIT_DIR = Path("/etc/systemd/system")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
PYTHON_PATH = Path("/usr/bin/python3")
SHADOW_EVIDENCE_ROOT = Path("/home/andris/hermes-deals-shadow-evidence/edeka")
MONITOR_EVIDENCE_ROOT = Path("/home/andris/hermes-deals-edeka-weekly-monitor")
CACHE_ROOT = Path("/home/andris/.cache/hermes-deals-edeka-shadow")
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SPAN_RE = re.compile(r"[1-9][0-9]*(?:ms|s|min|h|d|w)")
CALENDAR_RE = re.compile(r"[A-Za-z0-9*:/.,~+_ -]{1,160}")


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


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


def validate_source_repo(registration_sha: str) -> dict[str, str]:
    require(SHA40_RE.fullmatch(registration_sha) is not None, "registration SHA is invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository is missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated EDEKA audit repository is not a Git checkout")
    require(Path(__file__).resolve() == (SOURCE_REPO / INSTALLER_REL).resolve(), "installer must execute from the dedicated EDEKA audit checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == registration_sha, "dedicated EDEKA audit repository HEAD is not the registration SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated EDEKA audit repository is not clean")
    git("cat-file", "-e", f"{registration_sha}^{{commit}}")
    git("show-ref", "--verify", "--quiet", "refs/remotes/origin/main")
    ancestry = git("merge-base", "--is-ancestor", registration_sha, "refs/remotes/origin/main", check=False)
    require(ancestry.returncode == 0 and not ancestry.stderr, "registration SHA is not reachable from origin/main")

    expected = {PLANNER_REL: EXPECTED_PLANNER_BLOB, RUNTIME_REL: EXPECTED_RUNTIME_BLOB}
    for path, oid in expected.items():
        require(git_text("rev-parse", f"{registration_sha}:{path}") == oid, f"reviewed Git blob mismatch: {path}")
    installer_blob = git_text("rev-parse", f"{registration_sha}:{INSTALLER_REL}")
    require(git_text("hash-object", str(Path(__file__).resolve())) == installer_blob, "running installer bytes differ from the registration commit")
    return {**expected, INSTALLER_REL: installer_blob}


def validate_inputs(
    on_calendar: str,
    retry_delay: str,
    retry_window: str,
    max_attempts: int,
    timeout_start: str,
    runner_timeout_seconds: int,
) -> None:
    require("\n" not in on_calendar and "\r" not in on_calendar, "OnCalendar must be one line")
    require(CALENDAR_RE.fullmatch(on_calendar) is not None, "OnCalendar contains unsupported characters")
    for value, label in ((retry_delay, "retry delay"), (retry_window, "retry window"), (timeout_start, "timeout start")):
        require(SPAN_RE.fullmatch(value) is not None, f"{label} is invalid")
    require(2 <= max_attempts <= 5, "max attempts must be between 2 and 5")
    require(60 <= runner_timeout_seconds <= 7200, "runner timeout must be between 60 and 7200 seconds")


def run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=120,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"registration preflight failed: {Path(argv[0]).name}")
    return result


def run_as_andris(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8",
        *argv,
    ]
    return run(command, check=check)


def validate_generated_plan(
    plan: Mapping[str, Any],
    *,
    registration_sha: str,
    on_calendar: str,
    retry_delay: str,
    retry_window: str,
    max_attempts: int,
    timeout_start: str,
    runner_timeout_seconds: int,
    output_dir: Path,
) -> dict[str, str]:
    require(plan.get("schema_version") == 1, "monitor plan schema mismatch")
    require(plan.get("planner_version") == "edeka-weekly-monitor-activation-plan-v1", "monitor planner version mismatch")
    require(plan.get("repo_sha") == registration_sha, "monitor plan runtime identity mismatch")
    schedule = plan.get("schedule")
    require(isinstance(schedule, Mapping), "monitor plan schedule missing")
    expected_schedule = {
        "on_calendar": on_calendar,
        "persistent": True,
        "max_attempts_per_retry_window": max_attempts,
        "retry_delay": retry_delay,
        "retry_window": retry_window,
        "timeout_start": timeout_start,
        "runner_timeout_seconds": runner_timeout_seconds,
    }
    require(dict(schedule) == expected_schedule, "monitor plan schedule drift")
    require(plan.get("activation_requires_explicit_owner_authorization") is True, "owner activation gate missing")
    require(plan.get("preflight_before_mutation") is True, "preflight-before-mutation gate missing")
    require(plan.get("rollback_preserves_shadow_evidence_root") is True, "shadow evidence preservation gate missing")
    require(plan.get("rollback_preserves_monitor_evidence_root") is True, "monitor evidence preservation gate missing")
    require(plan.get("rollback_preserves_cache_root") is True, "cache preservation gate missing")
    for key in (
        "source_refetch_authorized",
        "systemd_change_authorized",
        "systemd_change_performed",
        "bounded_retry_authorized",
        "production_database_write_authorized",
        "review_write_authorized",
        "publication_authorized",
        "deployment_authorized",
    ):
        require(plan.get(key) is False, f"unsafe generated monitor plan flag: {key}")

    unit_sha = plan.get("unit_sha256")
    require(isinstance(unit_sha, Mapping) and set(unit_sha) == set(UNIT_NAMES), "monitor plan unit set mismatch")
    actual: dict[str, str] = {}
    for name in UNIT_NAMES:
        path = output_dir / name
        require(path.is_file() and not path.is_symlink(), f"generated unit missing: {name}")
        digest = sha_file(path)
        require(unit_sha.get(name) == digest, f"generated unit SHA mismatch: {name}")
        actual[name] = digest
    return actual


def generate_plan(
    registration_sha: str,
    *,
    on_calendar: str,
    retry_delay: str,
    retry_window: str,
    max_attempts: int,
    timeout_start: str,
    runner_timeout_seconds: int,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    planner = SOURCE_REPO / PLANNER_REL
    result = run_as_andris([
        str(PYTHON_PATH), str(planner),
        "--output-dir", str(output_dir),
        "--repo-root", str(SOURCE_REPO),
        "--repo-sha", registration_sha,
        "--python", str(PYTHON_PATH),
        "--shadow-evidence-root", str(SHADOW_EVIDENCE_ROOT),
        "--monitor-evidence-root", str(MONITOR_EVIDENCE_ROOT),
        "--cache-root", str(CACHE_ROOT),
        "--on-calendar", on_calendar,
        "--retry-delay", retry_delay,
        "--retry-window", retry_window,
        "--max-attempts", str(max_attempts),
        "--timeout-start", timeout_start,
        "--runner-timeout-seconds", str(runner_timeout_seconds),
    ])
    require(result.stdout.strip().startswith("{"), "monitor planner did not emit a plan")
    plan_path = output_dir / "activation-plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("generated activation plan JSON invalid") from exc
    require(isinstance(plan, dict), "generated activation plan root invalid")
    hashes = validate_generated_plan(
        plan,
        registration_sha=registration_sha,
        on_calendar=on_calendar,
        retry_delay=retry_delay,
        retry_window=retry_window,
        max_attempts=max_attempts,
        timeout_start=timeout_start,
        runner_timeout_seconds=runner_timeout_seconds,
        output_dir=output_dir,
    )
    run(["/usr/bin/systemd-analyze", "calendar", on_calendar])
    run(["/usr/bin/systemd-analyze", "verify", *(str(output_dir / name) for name in UNIT_NAMES)])
    return plan, hashes


def _primary_ids() -> tuple[int, int]:
    try:
        user = pwd.getpwnam(AUDIT_USER)
        group = grp.getgrgid(user.pw_gid)
    except KeyError as exc:
        raise RegistrationError("andris account or primary group is unavailable") from exc
    require(group.gr_gid == user.pw_gid, "andris primary group lookup drift")
    return user.pw_uid, user.pw_gid


def ensure_user_dir(path: Path, uid: int, gid: int) -> bool:
    if path.exists() or path.is_symlink():
        require(path.is_dir() and not path.is_symlink(), f"existing data root unsafe: {path}")
        info = path.stat()
        require(info.st_uid == uid and info.st_gid == gid and stat.S_IMODE(info.st_mode) == 0o700, f"existing data root metadata drift: {path}")
        return False
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"data-root parent is missing or unsafe: {path.parent}")
    path.mkdir(mode=0o700)
    os.chown(path, uid, gid)
    os.chmod(path, 0o700)
    return True


def ensure_root_dir(path: Path, mode: int = 0o755, *, create: bool = False) -> None:
    if not path.exists() and create:
        path.mkdir(parents=True, mode=mode)
        os.chown(path, 0, 0)
        os.chmod(path, mode)
    require(path.is_dir() and not path.is_symlink(), f"registration directory unsafe: {path}")
    info = path.stat()
    require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode, f"registration directory metadata mismatch: {path}")


def require_units_inactive_and_timer_not_enabled() -> None:
    for unit in UNIT_NAMES:
        active = run(["/usr/bin/systemctl", "is-active", unit], check=False)
        require(active.returncode != 0, f"unit is already active before non-activating registration: {unit}")
    enabled = run(["/usr/bin/systemctl", "is-enabled", TIMER_UNIT], check=False)
    state = enabled.stdout.strip()
    require(state not in {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}, "timer is already enabled before non-activating registration")


def write_exclusive_or_identical(path: Path, payload: bytes, mode: int, *, uid: int = 0, gid: int = 0) -> bool:
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), f"existing registration path unsafe: {path}")
        info = path.stat()
        require(info.st_uid == uid and info.st_gid == gid and stat.S_IMODE(info.st_mode) == mode, f"existing registration metadata drift: {path}")
        require(path.read_bytes() == payload, f"existing registration content drift: {path}")
        return False
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"registration parent is missing or unsafe: {path.parent}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.edeka-monitor-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        os.close(fd)
        fd = -1
        os.link(temp, path, follow_symlinks=False)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)
    return True


def build_registration_config(
    *,
    registration_sha: str,
    blobs: Mapping[str, str],
    on_calendar: str,
    retry_delay: str,
    retry_window: str,
    max_attempts: int,
    timeout_start: str,
    runner_timeout_seconds: int,
    unit_hashes: Mapping[str, str],
) -> dict[str, Any]:
    core = {
        "schema_version": 1,
        "registration_sha": registration_sha,
        "repo_root": str(SOURCE_REPO),
        "planner_blob": blobs[PLANNER_REL],
        "runtime_blob": blobs[RUNTIME_REL],
        "installer_blob": blobs[INSTALLER_REL],
        "schedule": {
            "on_calendar": on_calendar,
            "retry_delay": retry_delay,
            "retry_window": retry_window,
            "max_attempts": max_attempts,
            "timeout_start": timeout_start,
            "runner_timeout_seconds": runner_timeout_seconds,
        },
        "unit_sha256": {name: unit_hashes[name] for name in UNIT_NAMES},
        "shadow_evidence_root": str(SHADOW_EVIDENCE_ROOT),
        "monitor_evidence_root": str(MONITOR_EVIDENCE_ROOT),
        "cache_root": str(CACHE_ROOT),
        "unit_dir": str(UNIT_DIR),
        "daemon_reload_performed": False,
        "timer_enable_performed": False,
        "timer_start_performed": False,
        "source_refetch_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
    }
    return {**core, "registration_fingerprint_sha256": sha_bytes(canonical_bytes(core))}


def register_units(args: argparse.Namespace) -> dict[str, Any]:
    require(os.geteuid() == 0, "installer must run as root")
    validate_inputs(
        args.on_calendar,
        args.retry_delay,
        args.retry_window,
        args.max_attempts,
        args.timeout_start,
        args.runner_timeout_seconds,
    )
    blobs = validate_source_repo(args.registration_sha)
    uid, gid = _primary_ids()
    require_units_inactive_and_timer_not_enabled()

    with tempfile.TemporaryDirectory(prefix="hermes-edeka-monitor-register-", dir="/run") as temp_name:
        temp = Path(temp_name)
        os.chown(temp, uid, gid)
        os.chmod(temp, 0o700)
        _, unit_hashes = generate_plan(
            args.registration_sha,
            on_calendar=args.on_calendar,
            retry_delay=args.retry_delay,
            retry_window=args.retry_window,
            max_attempts=args.max_attempts,
            timeout_start=args.timeout_start,
            runner_timeout_seconds=args.runner_timeout_seconds,
            output_dir=temp,
        )

        ensure_root_dir(UNIT_DIR, 0o755)
        ensure_root_dir(CONFIG_DST.parent, 0o755, create=True)
        created_data_roots = {
            str(path): ensure_user_dir(path, uid, gid)
            for path in (SHADOW_EVIDENCE_ROOT, MONITOR_EVIDENCE_ROOT, CACHE_ROOT)
        }

        unit_changes: dict[str, bool] = {}
        for name in UNIT_NAMES:
            payload = (temp / name).read_bytes()
            require(sha_bytes(payload) == unit_hashes[name], f"unit bytes changed after preflight: {name}")
            unit_changes[name] = write_exclusive_or_identical(UNIT_DIR / name, payload, 0o644)

        config = build_registration_config(
            registration_sha=args.registration_sha,
            blobs=blobs,
            on_calendar=args.on_calendar,
            retry_delay=args.retry_delay,
            retry_window=args.retry_window,
            max_attempts=args.max_attempts,
            timeout_start=args.timeout_start,
            runner_timeout_seconds=args.runner_timeout_seconds,
            unit_hashes=unit_hashes,
        )
        config_changed = write_exclusive_or_identical(CONFIG_DST, canonical_bytes(config), 0o600)
        require_units_inactive_and_timer_not_enabled()

    return {
        "result": "PASS",
        "registration_sha": args.registration_sha,
        "registration_fingerprint_sha256": config["registration_fingerprint_sha256"],
        "unit_sha256": config["unit_sha256"],
        "unit_file_changes": unit_changes,
        "registration_config_changed": config_changed,
        "data_root_changes": created_data_roots,
        "daemon_reload_performed": False,
        "timer_enable_performed": False,
        "timer_start_performed": False,
        "source_refetch_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register exact EDEKA weekly monitoring unit files without loading or activating them.")
    parser.add_argument("--registration-sha", required=True)
    parser.add_argument("--on-calendar", required=True)
    parser.add_argument("--retry-delay", required=True)
    parser.add_argument("--retry-window", required=True)
    parser.add_argument("--max-attempts", type=int, required=True)
    parser.add_argument("--timeout-start", required=True)
    parser.add_argument("--runner-timeout-seconds", type=int, default=2700)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = register_units(args)
    except (OSError, UnicodeError, RegistrationError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"result": "BLOCKED", "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("EDEKA_WEEKLY_MONITOR_UNIT_REGISTRATION=PASS")
    print("SYSTEMD_DAEMON_RELOAD=false")
    print("SYSTEMD_TIMER_ENABLE=false")
    print("SYSTEMD_TIMER_START=false")
    print("SOURCE_REFETCH=false")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_WRITE=false")
    print("PRODUCTION_PUBLISH=false")
    print("PRODUCTION_DEPLOY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
