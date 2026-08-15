#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Mapping

SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
REGISTRATION_SHA = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
OLD_CONTROL_SHA = "9ffa65701a8ed05357aabb750591671604e3899b"
OLD_FINGERPRINT = "f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb"
NEW_FINGERPRINT = "970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947"
OLD_TIMER_SHA256 = "8f177a8752b9bc9684a87ad3f2f1cd5c367a915591ca6f66d31b0ff8189f34b8"
NEW_TIMER_SHA256 = "6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d"
OLD_DISPATCHER_BLOB = "8993e0059620afc5aeb4d66504e10f9deb5a99c8"
OLD_DISPATCHER_SHA256 = "6e8039c0f439254eaaa81200f18090b86494bbcc2da0f33aa741d6a1e3e74e32"
OLD_SCHEDULE = "Mon *-*-* 06:15:00 Europe/Berlin"
NEW_SCHEDULE = "Sun *-*-* 00:10:00 Europe/Berlin"
SERVICE_SHA256 = "d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de"
FAILURE_SHA256 = "c5faf2255c86d8908230449315e5a8b1813b61ae300d4c32899ada9e38c1e9b7"

SERVICE_UNIT = "hermes-edeka-weekly-monitor.service"
TIMER_UNIT = "hermes-edeka-weekly-monitor.timer"
FAILURE_UNIT = "hermes-edeka-weekly-monitor-failure@.service"
UNIT_DIR = Path("/etc/systemd/system")
REGISTRATION_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
CONTROL_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-control.json")
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-edeka-weekly-monitor-control")
MIGRATION_REL = "tools/runner/reschedule_edeka_weekly_monitor.py"
DISPATCHER_REL = "tools/runner/edeka_weekly_monitor_control.py"
AUTHOR_REL = "tools/github_edeka_weekly_monitor_control.py"
WORKFLOW_REL = ".github/workflows/hermes-edeka-weekly-monitor-control.yml"
SHA40_RE = re.compile(r"[0-9a-f]{40}")
ENABLED_STATES = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}

NEW_TIMER_BYTES = (
    "[Unit]\n"
    "Description=Hermes Deals EDEKA Patzer bounded weekly monitor timer\n"
    "OnFailure=hermes-edeka-weekly-monitor-failure@%n.service\n\n"
    "[Timer]\n"
    f"OnCalendar={NEW_SCHEDULE}\n"
    f"Unit={SERVICE_UNIT}\n"
    "Persistent=true\n"
    "AccuracySec=5min\n\n"
    "[Install]\n"
    "WantedBy=timers.target\n"
).encode("utf-8")


class RescheduleError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RescheduleError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def run(argv: list[str], *, check: bool = True, input_bytes: bytes | None = None, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        argv,
        input=input_bytes,
        stdin=subprocess.DEVNULL if input_bytes is None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
    )
    if check:
        require(result.returncode == 0, f"command failed: {Path(argv[0]).name}")
    return result


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
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
    return git(*args).stdout.decode("utf-8").strip()


def read_json_root(path: Path, mode: int, label: str) -> dict[str, Any]:
    require(regular_root_file(path, mode), f"{label} missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RescheduleError(f"{label} JSON invalid") from exc
    require(isinstance(value, dict), f"{label} root invalid")
    return value


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def systemctl_state(verb: str, unit: str) -> tuple[int, str]:
    result = run(["/usr/bin/systemctl", verb, unit], check=False)
    return result.returncode, result.stdout.decode("utf-8").strip()


def timer_enabled() -> bool:
    _, state = systemctl_state("is-enabled", TIMER_UNIT)
    return state in ENABLED_STATES


def unit_active(unit: str) -> bool:
    rc, state = systemctl_state("is-active", unit)
    return rc == 0 and state == "active"


def unit_failed(unit: str) -> bool:
    rc, state = systemctl_state("is-failed", unit)
    return rc == 0 and state == "failed"


def build_sudoers(control_sha: str, fingerprint: str) -> bytes:
    sudo_tag = "".join(("NO", "PASS", "WD", ":"))
    base = f"github-runner ALL=(root) {sudo_tag} {DISPATCH_DST}"
    return (
        f"{base} activate {control_sha} {fingerprint} source-refetch=authorized bounded-retries=authorized\n"
        f"{base} disable {control_sha} {fingerprint} source-refetch=forbidden bounded-retries=forbidden\n"
        f"{base} rollback {control_sha} {fingerprint} source-refetch=forbidden bounded-retries=forbidden\n"
    ).encode("utf-8")


def validate_sudoers(payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix="edeka-monitor-reschedule-sudoers-", dir="/run")
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o440)
        require(run(["/usr/sbin/visudo", "-cf", str(path)], check=False).returncode == 0, "generated sudoers policy failed validation")
    finally:
        path.unlink(missing_ok=True)


def validate_source(control_sha: str) -> tuple[str, bytes]:
    require(SHA40_RE.fullmatch(control_sha) is not None, "control SHA invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated EDEKA audit repository is not a Git checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == REGISTRATION_SHA, "dedicated EDEKA audit HEAD must remain pinned to registration SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated EDEKA audit repository is not clean")
    require(git_text("rev-parse", "refs/remotes/origin/main") == control_sha, "control SHA is not exact fetched origin/main")
    require(git("merge-base", "--is-ancestor", REGISTRATION_SHA, control_sha, check=False).returncode == 0, "control SHA does not descend from registered monitor source")
    require(git("merge-base", "--is-ancestor", OLD_CONTROL_SHA, control_sha, check=False).returncode == 0, "control SHA does not descend from registered owner control")

    running_blob = git_text("rev-parse", f"{control_sha}:{MIGRATION_REL}")
    require(git_blob_sha(Path(__file__).read_bytes()) == running_blob, "running reschedule tool differs from control commit")
    for path in (DISPATCHER_REL, AUTHOR_REL, WORKFLOW_REL):
        require(SHA40_RE.fullmatch(git_text("rev-parse", f"{control_sha}:{path}")) is not None, f"missing reviewed control source: {path}")

    dispatcher_blob = git_text("rev-parse", f"{control_sha}:{DISPATCHER_REL}")
    dispatcher = git("cat-file", "blob", dispatcher_blob).stdout
    require(git_blob_sha(dispatcher) == dispatcher_blob, "new dispatcher Git blob payload drift")
    require(dispatcher.startswith(b"#!/usr/bin/env python3\n"), "new dispatcher shebang drift")
    return dispatcher_blob, dispatcher


def validate_old_state() -> tuple[dict[str, Any], dict[str, Any], bytes]:
    registration = read_json_root(REGISTRATION_CONFIG, 0o600, "registration config")
    require(registration.get("registration_sha") == REGISTRATION_SHA, "registration SHA drift")
    require(registration.get("registration_fingerprint_sha256") == OLD_FINGERPRINT, "old registration fingerprint drift")
    core = {key: value for key, value in registration.items() if key != "registration_fingerprint_sha256"}
    require(sha256_bytes(canonical_bytes(core)) == OLD_FINGERPRINT, "old registration fingerprint recomputation mismatch")
    require(registration.get("schedule", {}).get("on_calendar") == OLD_SCHEDULE, "old schedule drift")
    unit_hashes = registration.get("unit_sha256")
    require(isinstance(unit_hashes, dict), "old unit hash map invalid")
    require(unit_hashes.get(SERVICE_UNIT) == SERVICE_SHA256, "service hash registration drift")
    require(unit_hashes.get(TIMER_UNIT) == OLD_TIMER_SHA256, "old timer hash registration drift")
    require(unit_hashes.get(FAILURE_UNIT) == FAILURE_SHA256, "failure hash registration drift")
    for name, expected in ((SERVICE_UNIT, SERVICE_SHA256), (TIMER_UNIT, OLD_TIMER_SHA256), (FAILURE_UNIT, FAILURE_SHA256)):
        path = UNIT_DIR / name
        require(regular_root_file(path, 0o644), f"installed unit missing or unsafe: {name}")
        require(sha256_file(path) == expected, f"installed unit content drift: {name}")

    control = read_json_root(CONTROL_CONFIG, 0o600, "control config")
    require(control.get("control_sha") == OLD_CONTROL_SHA, "old control SHA drift")
    require(control.get("registration_sha") == REGISTRATION_SHA, "old control registration SHA drift")
    require(control.get("registration_fingerprint_sha256") == OLD_FINGERPRINT, "old control fingerprint drift")
    require(control.get("dispatcher_blob") == OLD_DISPATCHER_BLOB, "old dispatcher blob drift")
    require(control.get("dispatcher_sha256") == OLD_DISPATCHER_SHA256, "old dispatcher SHA256 drift")
    require(regular_root_file(DISPATCH_DST, 0o755), "installed dispatcher missing or unsafe")
    old_dispatcher = DISPATCH_DST.read_bytes()
    require(git_blob_sha(old_dispatcher) == OLD_DISPATCHER_BLOB, "installed old dispatcher Git blob drift")
    require(sha256_bytes(old_dispatcher) == OLD_DISPATCHER_SHA256, "installed old dispatcher SHA256 drift")

    old_sudoers = build_sudoers(OLD_CONTROL_SHA, OLD_FINGERPRINT)
    require(regular_root_file(SUDOERS_DST, 0o440), "installed sudoers missing or unsafe")
    require(SUDOERS_DST.read_bytes() == old_sudoers, "installed sudoers content drift")

    require(timer_enabled(), "weekly timer is not enabled before reschedule")
    require(unit_active(TIMER_UNIT), "weekly timer is not active before reschedule")
    require(not unit_failed(TIMER_UNIT), "weekly timer is failed before reschedule")
    require(not unit_active(SERVICE_UNIT), "weekly service is active before reschedule")
    require(not unit_failed(SERVICE_UNIT), "weekly service is failed before reschedule")
    return registration, control, old_sudoers


def build_new_registration(old: Mapping[str, Any]) -> dict[str, Any]:
    registration = copy.deepcopy(dict(old))
    schedule = dict(registration["schedule"])
    schedule["on_calendar"] = NEW_SCHEDULE
    registration["schedule"] = schedule
    unit_hashes = dict(registration["unit_sha256"])
    unit_hashes[TIMER_UNIT] = NEW_TIMER_SHA256
    registration["unit_sha256"] = unit_hashes
    core = {key: value for key, value in registration.items() if key != "registration_fingerprint_sha256"}
    fingerprint = sha256_bytes(canonical_bytes(core))
    require(fingerprint == NEW_FINGERPRINT, "new registration fingerprint derivation mismatch")
    registration["registration_fingerprint_sha256"] = fingerprint
    return registration


def build_new_control(old: Mapping[str, Any], control_sha: str, dispatcher_blob: str, dispatcher: bytes) -> dict[str, Any]:
    control = copy.deepcopy(dict(old))
    control["control_sha"] = control_sha
    control["dispatcher_blob"] = dispatcher_blob
    control["dispatcher_sha256"] = sha256_bytes(dispatcher)
    control["registration_fingerprint_sha256"] = NEW_FINGERPRINT
    return control


def atomic_replace(path: Path, payload: bytes, mode: int) -> None:
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"unsafe parent: {path.parent}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.edeka-reschedule-", dir=path.parent)
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
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)


def verify_new_files(new_registration: Mapping[str, Any], control_sha: str, dispatcher_blob: str, dispatcher: bytes, new_sudoers: bytes) -> None:
    require(sha256_file(UNIT_DIR / TIMER_UNIT) == NEW_TIMER_SHA256, "new timer bytes not installed")
    stored = read_json_root(REGISTRATION_CONFIG, 0o600, "new registration config")
    require(stored == new_registration, "new registration config drift")
    control = read_json_root(CONTROL_CONFIG, 0o600, "new control config")
    require(control.get("control_sha") == control_sha, "new control SHA drift")
    require(control.get("registration_fingerprint_sha256") == NEW_FINGERPRINT, "new control fingerprint drift")
    require(control.get("dispatcher_blob") == dispatcher_blob, "new control dispatcher blob drift")
    require(control.get("dispatcher_sha256") == sha256_bytes(dispatcher), "new control dispatcher SHA drift")
    require(DISPATCH_DST.read_bytes() == dispatcher, "new dispatcher bytes drift")
    require(SUDOERS_DST.read_bytes() == new_sudoers, "new sudoers bytes drift")


def preflight_candidate() -> None:
    require(sha256_bytes(NEW_TIMER_BYTES) == NEW_TIMER_SHA256, "new timer constant hash mismatch")
    run(["/usr/bin/systemd-analyze", "calendar", NEW_SCHEDULE])
    with tempfile.TemporaryDirectory(prefix="edeka-monitor-reschedule-", dir="/run") as temp_dir:
        timer_path = Path(temp_dir) / TIMER_UNIT
        timer_path.write_bytes(NEW_TIMER_BYTES)
        os.chmod(timer_path, 0o644)
        run([
            "/usr/bin/systemd-analyze", "verify",
            str(UNIT_DIR / SERVICE_UNIT), str(timer_path), str(UNIT_DIR / FAILURE_UNIT),
        ])


def restore_old(old_bytes: Mapping[Path, tuple[bytes, int]]) -> bool:
    run(["/usr/bin/systemctl", "stop", TIMER_UNIT], check=False)
    run(["/usr/bin/systemctl", "stop", SERVICE_UNIT], check=False)
    ok = True
    for path, (payload, mode) in old_bytes.items():
        try:
            atomic_replace(path, payload, mode)
        except Exception:
            ok = False
    run(["/usr/bin/systemctl", "daemon-reload"], check=False)
    run(["/usr/bin/systemctl", "start", TIMER_UNIT], check=False)
    return ok and timer_enabled() and unit_active(TIMER_UNIT)


def reschedule(control_sha: str, old_fingerprint: str, new_fingerprint: str, catchup_authority: str) -> dict[str, Any]:
    require(os.geteuid() == 0, "reschedule must run as root")
    require(old_fingerprint == OLD_FINGERPRINT, "old fingerprint authorization mismatch")
    require(new_fingerprint == NEW_FINGERPRINT, "new fingerprint authorization mismatch")
    require(catchup_authority == "persistent-catchup=authorized", "Persistent timer catch-up authority missing")

    dispatcher_blob, dispatcher = validate_source(control_sha)
    old_registration, old_control, old_sudoers = validate_old_state()
    preflight_candidate()
    new_registration = build_new_registration(old_registration)
    new_control = build_new_control(old_control, control_sha, dispatcher_blob, dispatcher)
    new_sudoers = build_sudoers(control_sha, NEW_FINGERPRINT)
    validate_sudoers(new_sudoers)

    old_bytes = {
        UNIT_DIR / TIMER_UNIT: ((UNIT_DIR / TIMER_UNIT).read_bytes(), 0o644),
        REGISTRATION_CONFIG: (REGISTRATION_CONFIG.read_bytes(), 0o600),
        DISPATCH_DST: (DISPATCH_DST.read_bytes(), 0o755),
        CONTROL_CONFIG: (CONTROL_CONFIG.read_bytes(), 0o600),
        SUDOERS_DST: (SUDOERS_DST.read_bytes(), 0o440),
    }
    try:
        run(["/usr/bin/systemctl", "stop", TIMER_UNIT])
        require(not unit_active(TIMER_UNIT), "timer did not stop for atomic reschedule")
        require(not unit_active(SERVICE_UNIT), "service became active during reschedule prewrite")

        atomic_replace(UNIT_DIR / TIMER_UNIT, NEW_TIMER_BYTES, 0o644)
        atomic_replace(REGISTRATION_CONFIG, canonical_bytes(new_registration), 0o600)
        atomic_replace(DISPATCH_DST, dispatcher, 0o755)
        atomic_replace(CONTROL_CONFIG, canonical_bytes(new_control), 0o600)
        atomic_replace(SUDOERS_DST, new_sudoers, 0o440)

        run(["/usr/bin/systemctl", "daemon-reload"])
        run(["/usr/bin/systemctl", "start", TIMER_UNIT])
        require(timer_enabled(), "timer lost enabled state during reschedule")
        require(unit_active(TIMER_UNIT), "timer did not become active after reschedule")
        require(not unit_failed(TIMER_UNIT), "timer is failed after reschedule")
        verify_new_files(new_registration, control_sha, dispatcher_blob, dispatcher, new_sudoers)
    except Exception:
        require(restore_old(old_bytes), "reschedule failed and exact old state could not be restored")
        raise

    service_active = unit_active(SERVICE_UNIT)
    return {
        "schema_version": 1,
        "result": "PASS",
        "operation": "reschedule",
        "registration_sha": REGISTRATION_SHA,
        "control_sha": control_sha,
        "old_registration_fingerprint_sha256": OLD_FINGERPRINT,
        "new_registration_fingerprint_sha256": NEW_FINGERPRINT,
        "old_on_calendar": OLD_SCHEDULE,
        "new_on_calendar": NEW_SCHEDULE,
        "old_timer_sha256": OLD_TIMER_SHA256,
        "new_timer_sha256": NEW_TIMER_SHA256,
        "dispatcher_blob": dispatcher_blob,
        "dispatcher_sha256": sha256_bytes(dispatcher),
        "systemd_change_performed": True,
        "daemon_reload_performed": True,
        "timer_enable_performed": False,
        "timer_stop_start_performed": True,
        "timer_enabled": True,
        "timer_active": True,
        "service_active_after_reschedule": service_active,
        "source_refetch_authorized": True,
        "source_refetch_may_have_been_triggered": True,
        "service_active_observed_after_reschedule": service_active,
        "bounded_retry_authorized": True,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
        "rollback_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atomically reschedule the registered EDEKA weekly monitor timer.")
    parser.add_argument("--control-sha", required=True)
    parser.add_argument("--old-fingerprint", required=True)
    parser.add_argument("--new-fingerprint", required=True)
    parser.add_argument("--persistent-catchup-authority", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = reschedule(
            args.control_sha,
            args.old_fingerprint,
            args.new_fingerprint,
            args.persistent_catchup_authority,
        )
    except (OSError, UnicodeError, ValueError, RescheduleError, subprocess.SubprocessError) as exc:
        print(json.dumps({"schema_version": 1, "result": "BLOCKED", "operation": "reschedule", "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    print("EDEKA_WEEKLY_MONITOR_RESCHEDULE=PASS")
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
