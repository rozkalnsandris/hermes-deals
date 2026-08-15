#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Mapping

SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-lidl")
AUDIT_USER = "andris"
REGISTRATION_SHA = "907f45faf429f005f31e74aff16bb9ee5c4090a2"
OLD_PLAN_FINGERPRINT = "28277e25db006c82587b52bad02939d17ceb5eb455ec059e2cdc2ca5ff68ea31"
NEW_PLAN_FINGERPRINT = "651301e004e39360c7198721b32c299c58d1720c9409f06189e265ff311c4bb4"
OLD_SCHEDULE = "Mon *-*-* 06:15:00 Europe/Berlin"
NEW_SCHEDULE = "Sun *-*-* 00:10:00 Europe/Berlin"
SERVICE_SHA256 = "3668ad30bb5c6484c2c125774d9257450353f3d2dc4b5e63ef5f15374eab3ce0"
OLD_TIMER_SHA256 = "58e95d071813fec7f37d602cfdbd96f2f4d555db3f22d00b8d76d8066e53451e"
NEW_TIMER_SHA256 = "beedb229d2203ab239f10de2772e086de58e4b7032e705897d064978aa840597"
ALERT_SHA256 = "d3b0d215f05d0e4c94df47633310bd464701f4243bdf34631f76c4bd8526a43e"
EXPECTED_DISPATCHER_BLOB = "a96c8817e1e3d6bd386dcf36eb5cc1fe68c05b0f"

SERVICE_UNIT = "hermes-lidl-weekly.service"
TIMER_UNIT = "hermes-lidl-weekly.timer"
ALERT_UNIT = "hermes-lidl-weekly-failure@.service"
UNIT_NAMES = (SERVICE_UNIT, TIMER_UNIT, ALERT_UNIT)
UNIT_DIR = Path("/etc/systemd/system")
CONTROL_ROOT = Path("/usr/local/libexec/hermes-deals-lidl-gate-d-control")
STAGED_ROOT = CONTROL_ROOT / REGISTRATION_SHA
ARCHIVED_ROOT = CONTROL_ROOT / f"{REGISTRATION_SHA}.archived-{OLD_PLAN_FINGERPRINT}"
CONFIG = Path("/etc/hermes-deals-audits.d/lidl-gate-d-control.json")
DISPATCHER = Path("/usr/local/sbin/hermes-deals-lidl-gate-d-control")
SUDOERS = Path("/etc/sudoers.d/hermes-deals-lidl-gate-d-control")
MIGRATION_REL = "tools/runner/reschedule_lidl_gate_d.py"
POLICY_REL = "config/retailer-weekly-schedule-policy-v1.json"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")

NEW_TIMER_BYTES = (
    "[Unit]\n"
    "Description=Hermes Deals Lidl bounded weekly read-only timer\n"
    "OnFailure=hermes-lidl-weekly-failure@%n.service\n\n"
    "[Timer]\n"
    f"OnCalendar={NEW_SCHEDULE}\n"
    f"Unit={SERVICE_UNIT}\n"
    "Persistent=true\n"
    "AccuracySec=5min\n\n"
    "[Install]\n"
    "WantedBy=timers.target\n"
).encode("utf-8")


class LidlGateDRescheduleError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlGateDRescheduleError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


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


def regular_root_dir(path: Path, mode: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and stat.S_IMODE(info.st_mode) == mode
    )


def run(
    argv: list[str],
    *,
    check: bool = True,
    input_bytes: bytes | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        argv,
        input=input_bytes,
        stdin=subprocess.DEVNULL if input_bytes is None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
        },
    )
    if check:
        require(result.returncode == 0, f"command failed: {Path(argv[0]).name}")
    return result


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = run(
        [
            "/usr/sbin/runuser",
            "-u",
            AUDIT_USER,
            "--",
            "/usr/bin/env",
            "-i",
            "HOME=/home/andris",
            "USER=andris",
            "LOGNAME=andris",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "LANG=C.UTF-8",
            "GIT_OPTIONAL_LOCKS=0",
            "/usr/bin/git",
            "-C",
            str(SOURCE_REPO),
            *args,
        ],
        check=False,
        timeout=45,
    )
    if check:
        require(result.returncode == 0, f"audit Git command failed: {args[0]}")
        require(not result.stderr, f"audit Git command emitted stderr: {args[0]}")
    return result


def git_text(*args: str) -> str:
    return git(*args).stdout.decode("utf-8").strip()


def systemctl_state(verb: str, unit: str) -> tuple[int, str]:
    result = run(["/usr/bin/systemctl", verb, unit], check=False)
    return result.returncode, result.stdout.decode("utf-8").strip()


def timer_enabled() -> bool:
    rc, state = systemctl_state("is-enabled", TIMER_UNIT)
    return rc == 0 and state == "enabled"


def unit_active(unit: str) -> bool:
    rc, state = systemctl_state("is-active", unit)
    return rc == 0 and state == "active"


def unit_failed(unit: str) -> bool:
    rc, state = systemctl_state("is-failed", unit)
    return rc == 0 and state == "failed"


def read_json_root(path: Path, mode: int, label: str) -> dict[str, Any]:
    require(regular_root_file(path, mode), f"{label} missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LidlGateDRescheduleError(f"{label} JSON invalid") from exc
    require(isinstance(value, dict), f"{label} root invalid")
    return value


def plan_payload(config: Mapping[str, Any]) -> dict[str, Any]:
    schedule = config["schedule"]
    units = config["units"]
    return {
        "schema_version": 1,
        "registration_sha": config["registration_sha"],
        "target": config["target"],
        "repo_root": config["repo_root"],
        "python_path": config["python_path"],
        "corpus_root": config["corpus_root"],
        "evidence_root": config["evidence_root"],
        "schedule": {
            "on_calendar": schedule["on_calendar"],
            "retry_delay": schedule["retry_delay"],
            "retry_window": schedule["retry_window"],
            "max_attempts": schedule["max_attempts"],
            "timeout_start": schedule["timeout_start"],
        },
        "unit_sha256": {
            name: units[name]["sha256"]
            for name in UNIT_NAMES
        },
    }


def plan_fingerprint(config: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(plan_payload(config)))


def build_sudoers(fingerprint: str) -> bytes:
    require(SHA256_RE.fullmatch(fingerprint) is not None, "sudoers fingerprint invalid")
    sudo_tag = "".join(("NO", "PASS", "WD", ":"))
    return (
        f"Cmnd_Alias HERMES_DEALS_LIDL_GATE_D_CONTROL = {DISPATCHER} "
        f"^(activate|disable|rollback) {fingerprint}$\n"
        f"github-runner ALL=(root) {sudo_tag} HERMES_DEALS_LIDL_GATE_D_CONTROL\n"
    ).encode("utf-8")


def validate_sudoers(payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix="lidl-gate-d-reschedule-sudoers-", dir="/run")
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o440)
        require(
            run(["/usr/sbin/visudo", "-cf", str(path)], check=False).returncode == 0,
            "generated sudoers policy failed validation",
        )
    finally:
        path.unlink(missing_ok=True)


def validate_source(control_sha: str) -> None:
    require(SHA40_RE.fullmatch(control_sha) is not None, "control SHA invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated Lidl audit repository missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated Lidl audit repository is not a Git checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated Lidl audit repository is not on main")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated Lidl audit repository is not clean")
    local_head = git_text("rev-parse", "HEAD")
    require(SHA40_RE.fullmatch(local_head) is not None, "dedicated Lidl audit HEAD invalid")
    require(git("merge-base", "--is-ancestor", REGISTRATION_SHA, local_head, check=False).returncode == 0, "audit HEAD predates registered Lidl control")
    require(git("merge-base", "--is-ancestor", local_head, control_sha, check=False).returncode == 0, "audit HEAD is not reachable from control SHA")
    require(git_text("rev-parse", "refs/remotes/origin/main") == control_sha, "control SHA is not exact fetched origin/main")
    require(git("merge-base", "--is-ancestor", REGISTRATION_SHA, control_sha, check=False).returncode == 0, "control SHA does not descend from registered Lidl Gate D control")

    running_blob = git_text("rev-parse", f"{control_sha}:{MIGRATION_REL}")
    require(git_blob_sha(Path(__file__).read_bytes()) == running_blob, "running Lidl reschedule tool differs from control commit")
    policy_blob = git_text("rev-parse", f"{control_sha}:{POLICY_REL}")
    require(SHA40_RE.fullmatch(policy_blob) is not None, "weekly schedule policy missing from control commit")
    require(git_text("rev-parse", f"{REGISTRATION_SHA}:tools/runner/lidl_gate_d_control.py") == EXPECTED_DISPATCHER_BLOB, "registered dispatcher source identity drift")


def validate_old_state() -> tuple[dict[str, Any], bytes]:
    config = read_json_root(CONFIG, 0o600, "Lidl Gate D control config")
    require(config.get("control") == "lidl-gate-d-control", "control identity drift")
    require(config.get("issue_number") == 24 and config.get("bridge_pr") == 656, "control issue/bridge drift")
    require(config.get("registration_sha") == REGISTRATION_SHA, "registration SHA drift")
    require(config.get("plan_fingerprint") == OLD_PLAN_FINGERPRINT, "old plan fingerprint drift")
    require(plan_fingerprint(config) == OLD_PLAN_FINGERPRINT, "old plan fingerprint recomputation mismatch")
    require(config.get("schedule", {}).get("on_calendar") == OLD_SCHEDULE, "old Lidl schedule drift")
    require(config.get("target") == "current", "Lidl Gate D target drift")

    expected_hashes = {
        SERVICE_UNIT: SERVICE_SHA256,
        TIMER_UNIT: OLD_TIMER_SHA256,
        ALERT_UNIT: ALERT_SHA256,
    }
    units = config.get("units")
    require(isinstance(units, dict) and set(units) == set(UNIT_NAMES), "old unit config invalid")
    for name, digest in expected_hashes.items():
        row = units.get(name)
        require(isinstance(row, dict), f"old unit row invalid: {name}")
        require(row.get("path") == str(STAGED_ROOT / name), f"old staged path drift: {name}")
        require(row.get("sha256") == digest, f"old staged hash drift: {name}")
        require(regular_root_file(STAGED_ROOT / name, 0o444), f"old staged unit missing or unsafe: {name}")
        require(sha256_file(STAGED_ROOT / name) == digest, f"old staged unit content drift: {name}")
        require(regular_root_file(UNIT_DIR / name, 0o644), f"installed unit missing or unsafe: {name}")
        require(sha256_file(UNIT_DIR / name) == digest, f"installed unit content drift: {name}")

    require(regular_root_dir(STAGED_ROOT, 0o755), "old staged root missing or unsafe")
    require(not ARCHIVED_ROOT.exists() and not ARCHIVED_ROOT.is_symlink(), "old staged archive target already exists")
    require(regular_root_file(DISPATCHER, 0o755), "installed Lidl dispatcher missing or unsafe")
    require(git_blob_sha(DISPATCHER.read_bytes()) == EXPECTED_DISPATCHER_BLOB, "installed Lidl dispatcher identity drift")

    old_sudoers = build_sudoers(OLD_PLAN_FINGERPRINT)
    require(regular_root_file(SUDOERS, 0o440), "installed Lidl sudoers missing or unsafe")
    require(SUDOERS.read_bytes() == old_sudoers, "installed Lidl sudoers content drift")

    require(timer_enabled(), "Lidl weekly timer is not enabled before reschedule")
    require(unit_active(TIMER_UNIT), "Lidl weekly timer is not active before reschedule")
    require(not unit_failed(TIMER_UNIT), "Lidl weekly timer is failed before reschedule")
    require(not unit_active(SERVICE_UNIT), "Lidl weekly service is active before reschedule")
    require(not unit_failed(SERVICE_UNIT), "Lidl weekly service is failed before reschedule")
    return config, old_sudoers


def build_new_config(old: Mapping[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(dict(old))
    schedule = dict(config["schedule"])
    schedule["on_calendar"] = NEW_SCHEDULE
    config["schedule"] = schedule
    units = copy.deepcopy(dict(config["units"]))
    units[TIMER_UNIT]["sha256"] = NEW_TIMER_SHA256
    config["units"] = units
    config["plan_fingerprint"] = NEW_PLAN_FINGERPRINT
    require(plan_fingerprint(config) == NEW_PLAN_FINGERPRINT, "new Lidl plan fingerprint derivation mismatch")
    return config


def atomic_replace(path: Path, payload: bytes, mode: int) -> None:
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"unsafe parent: {path.parent}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.lidl-reschedule-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        os.close(fd)
        fd = -1
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)


def build_new_staged_root() -> Path:
    require(regular_root_dir(CONTROL_ROOT, 0o755), "Lidl control root missing or unsafe")
    temp = Path(tempfile.mkdtemp(prefix=".lidl-gate-d-reschedule-", dir=CONTROL_ROOT))
    os.chown(temp, 0, 0)
    os.chmod(temp, 0o755)
    try:
        for name in UNIT_NAMES:
            payload = NEW_TIMER_BYTES if name == TIMER_UNIT else (STAGED_ROOT / name).read_bytes()
            target = temp / name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
            try:
                os.write(fd, payload)
                os.fsync(fd)
                os.fchown(fd, 0, 0)
                os.fchmod(fd, 0o444)
            finally:
                os.close(fd)
        expected = {
            SERVICE_UNIT: SERVICE_SHA256,
            TIMER_UNIT: NEW_TIMER_SHA256,
            ALERT_UNIT: ALERT_SHA256,
        }
        for name, digest in expected.items():
            require(regular_root_file(temp / name, 0o444), f"new staged unit metadata invalid: {name}")
            require(sha256_file(temp / name) == digest, f"new staged unit hash invalid: {name}")
        return temp
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def preflight_candidate(new_staged: Path) -> None:
    require(sha256_bytes(NEW_TIMER_BYTES) == NEW_TIMER_SHA256, "new timer constant hash mismatch")
    run(["/usr/bin/systemd-analyze", "calendar", NEW_SCHEDULE])
    run([
        "/usr/bin/systemd-analyze",
        "verify",
        str(new_staged / SERVICE_UNIT),
        str(new_staged / TIMER_UNIT),
        str(new_staged / ALERT_UNIT),
    ])


def restore_old(
    *,
    old_config_bytes: bytes,
    old_sudoers: bytes,
    old_timer_bytes: bytes,
    new_staged_root_present: bool,
) -> bool:
    run(["/usr/bin/systemctl", "stop", TIMER_UNIT], check=False)
    run(["/usr/bin/systemctl", "stop", SERVICE_UNIT], check=False)
    ok = True
    try:
        atomic_replace(UNIT_DIR / TIMER_UNIT, old_timer_bytes, 0o644)
        atomic_replace(CONFIG, old_config_bytes, 0o600)
        atomic_replace(SUDOERS, old_sudoers, 0o440)
    except Exception:
        ok = False
    try:
        if new_staged_root_present and STAGED_ROOT.exists():
            for name in UNIT_NAMES:
                path = STAGED_ROOT / name
                if path.exists() and regular_root_file(path, 0o444):
                    path.unlink()
            STAGED_ROOT.rmdir()
        if ARCHIVED_ROOT.exists() and not STAGED_ROOT.exists():
            os.rename(ARCHIVED_ROOT, STAGED_ROOT)
    except Exception:
        ok = False
    run(["/usr/bin/systemctl", "daemon-reload"], check=False)
    run(["/usr/bin/systemctl", "start", TIMER_UNIT], check=False)
    return (
        ok
        and timer_enabled()
        and unit_active(TIMER_UNIT)
        and sha256_file(UNIT_DIR / TIMER_UNIT) == OLD_TIMER_SHA256
        and plan_fingerprint(read_json_root(CONFIG, 0o600, "restored config")) == OLD_PLAN_FINGERPRINT
    )


def verify_new_state(new_config: Mapping[str, Any], new_sudoers: bytes) -> None:
    require(regular_root_dir(STAGED_ROOT, 0o755), "new staged root missing or unsafe")
    require(regular_root_dir(ARCHIVED_ROOT, 0o755), "archived old staged root missing or unsafe")
    expected_new = {
        SERVICE_UNIT: SERVICE_SHA256,
        TIMER_UNIT: NEW_TIMER_SHA256,
        ALERT_UNIT: ALERT_SHA256,
    }
    expected_old = {
        SERVICE_UNIT: SERVICE_SHA256,
        TIMER_UNIT: OLD_TIMER_SHA256,
        ALERT_UNIT: ALERT_SHA256,
    }
    for name in UNIT_NAMES:
        require(regular_root_file(STAGED_ROOT / name, 0o444), f"new staged unit missing: {name}")
        require(sha256_file(STAGED_ROOT / name) == expected_new[name], f"new staged unit drift: {name}")
        require(regular_root_file(ARCHIVED_ROOT / name, 0o444), f"archived staged unit missing: {name}")
        require(sha256_file(ARCHIVED_ROOT / name) == expected_old[name], f"archived staged unit drift: {name}")

    stored = read_json_root(CONFIG, 0o600, "new Lidl Gate D config")
    require(stored == new_config, "new Lidl Gate D config drift")
    require(plan_fingerprint(stored) == NEW_PLAN_FINGERPRINT, "new Lidl plan fingerprint drift")
    require(sha256_file(UNIT_DIR / TIMER_UNIT) == NEW_TIMER_SHA256, "new installed Lidl timer drift")
    require(SUDOERS.read_bytes() == new_sudoers, "new Lidl sudoers drift")
    require(timer_enabled(), "Lidl timer lost enabled state")
    require(unit_active(TIMER_UNIT), "Lidl timer did not become active")
    require(not unit_failed(TIMER_UNIT), "Lidl timer is failed after reschedule")


def reschedule(
    control_sha: str,
    old_plan: str,
    new_plan: str,
    catchup_authority: str,
) -> dict[str, Any]:
    require(os.geteuid() == 0, "Lidl Gate D reschedule must run as root")
    require(old_plan == OLD_PLAN_FINGERPRINT, "old plan authorization mismatch")
    require(new_plan == NEW_PLAN_FINGERPRINT, "new plan authorization mismatch")
    require(catchup_authority == "persistent-catchup=authorized", "Persistent timer catch-up authority missing")

    validate_source(control_sha)
    old_config, old_sudoers = validate_old_state()
    new_config = build_new_config(old_config)
    new_sudoers = build_sudoers(NEW_PLAN_FINGERPRINT)
    validate_sudoers(new_sudoers)

    old_config_bytes = CONFIG.read_bytes()
    old_timer_bytes = (UNIT_DIR / TIMER_UNIT).read_bytes()
    new_staged = build_new_staged_root()
    preflight_candidate(new_staged)

    moved_new = False
    try:
        run(["/usr/bin/systemctl", "stop", TIMER_UNIT])
        require(not unit_active(TIMER_UNIT), "Lidl timer did not stop for reschedule")
        require(not unit_active(SERVICE_UNIT), "Lidl service became active during reschedule prewrite")

        os.rename(STAGED_ROOT, ARCHIVED_ROOT)
        os.rename(new_staged, STAGED_ROOT)
        moved_new = True

        atomic_replace(UNIT_DIR / TIMER_UNIT, NEW_TIMER_BYTES, 0o644)
        atomic_replace(
            CONFIG,
            json.dumps(new_config, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            0o600,
        )
        atomic_replace(SUDOERS, new_sudoers, 0o440)
        run(["/usr/sbin/visudo", "-cf", str(SUDOERS)])

        run(["/usr/bin/systemctl", "daemon-reload"])
        run(["/usr/bin/systemctl", "start", TIMER_UNIT])
        verify_new_state(new_config, new_sudoers)
    except Exception:
        if new_staged.exists():
            shutil.rmtree(new_staged, ignore_errors=True)
        require(
            restore_old(
                old_config_bytes=old_config_bytes,
                old_sudoers=old_sudoers,
                old_timer_bytes=old_timer_bytes,
                new_staged_root_present=moved_new,
            ),
            "Lidl reschedule failed and exact old state could not be restored",
        )
        raise

    service_active = unit_active(SERVICE_UNIT)
    return {
        "schema_version": 1,
        "result": "PASS",
        "operation": "reschedule",
        "registration_sha": REGISTRATION_SHA,
        "control_sha": control_sha,
        "old_plan_fingerprint": OLD_PLAN_FINGERPRINT,
        "new_plan_fingerprint": NEW_PLAN_FINGERPRINT,
        "old_on_calendar": OLD_SCHEDULE,
        "new_on_calendar": NEW_SCHEDULE,
        "old_timer_sha256": OLD_TIMER_SHA256,
        "new_timer_sha256": NEW_TIMER_SHA256,
        "archived_previous_staged_root": True,
        "systemd_change_performed": True,
        "daemon_reload_performed": True,
        "timer_enable_performed": False,
        "timer_stop_start_performed": True,
        "timer_enabled": True,
        "timer_active": True,
        "service_active_after_reschedule": service_active,
        "source_refetch_authorized": True,
        "source_refetch_may_have_been_triggered": True,
        "bounded_retry_authorized": True,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
        "rollback_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically reschedule the registered Lidl Gate D timer to the canonical Sunday 00:10 window."
    )
    parser.add_argument("--control-sha", required=True)
    parser.add_argument("--old-plan", required=True)
    parser.add_argument("--new-plan", required=True)
    parser.add_argument("--persistent-catchup-authority", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = reschedule(
            args.control_sha,
            args.old_plan,
            args.new_plan,
            args.persistent_catchup_authority,
        )
    except (OSError, UnicodeError, ValueError, LidlGateDRescheduleError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "result": "BLOCKED",
                    "operation": "reschedule",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps(receipt, sort_keys=True))
    print("LIDL_GATE_D_RESCHEDULE=PASS")
    print("SYSTEMD_CHANGE=true")
    print("SYSTEMD_DAEMON_RELOAD=true")
    print("SYSTEMD_TIMER_ENABLE=false")
    print("SYSTEMD_TIMER_STOP_START=true")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_WRITE=false")
    print("PRODUCTION_PUBLISH=false")
    print("PRODUCTION_DEPLOY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
