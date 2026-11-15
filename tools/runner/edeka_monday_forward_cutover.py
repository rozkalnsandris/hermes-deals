#!/usr/bin/env python3
"""Owner-gated, fail-closed EDEKA #1183 Monday cutover. No implicit LIVE grant.

Input is an *already present* exact Git object, never an unpinned download.
Before LIVE, use --phase=preflight. --phase=apply requires a separately
recorded exact owner authorization for this host, source, control and effects.
There is no automatic retry, cleanup, rollback, reset-failed or reboot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from types import ModuleType
from zoneinfo import ZoneInfo


APP_SOURCE = "684b562084492eebecc76a898b1b5d92e6a8c2e4"
OLD_SOURCE = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
EXPECTED_NEW_FP = "19162a6e25844ff21f96f385e11715cecc34d8ede8dad971c03381d911aa0957"
EXPECTED_NEW_REG_SHA256 = "6fa3268c6add7e0356654a231b7d1f9dee87d06d76d6949a861cd6278cc95d7e"
EXPECTED_NEW_SERVICE_SHA256 = "d642a9e922a28dfeb982f9930b5091609fd1eebea7e7e27998a8486ab3f77824"
EXPECTED_NEW_TIMER_SHA256 = "214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178"
EXPECTED_HELPER_BLOB = "3691f5c28e8e10d06f7ca0a96728257db2268cc1"
APP_ROOT = Path("/home/andris/hermes-deals-audit-source-edeka")
UNIT_ROOT = Path("/etc/systemd/system")
REG_PATH = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
CTL_PATH = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-control.json")
DISPATCHER_PATH = Path("/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control")
SUDOERS_PATH = Path("/etc/sudoers.d/hermes-deals-edeka-weekly-monitor-control")
LOCK = Path("/run/lock/hermes-deals-edeka-monday-cutover.lock")
PERSISTENT_STAMP = Path("/var/lib/systemd/timers/stamp-hermes-edeka-weekly-monitor.timer")
SERVICE = "hermes-edeka-weekly-monitor.service"
TIMER = "hermes-edeka-weekly-monitor.timer"
ALERT = "hermes-edeka-weekly-monitor-failure@.service"
SELF_REL = "tools/runner/edeka_monday_forward_cutover.py"
DISPATCHER_REL = "tools/runner/edeka_weekly_monitor_control_monday.py"
HELPER_REL = "tools/edeka_monday_cutover_readonly_preflight.py"
RUNNER_REL = "tools/run-hermes-deals-edeka-shadow-cycle-v01.sh"
RUNTIME_MANIFEST_REL = "backend/locks/manifest.json"
RUNTIME_LOCK_REL = "backend/locks/runtime-py313.txt"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
LIVE_TOKEN = "EXACT-ONE-SHOT-MONDAY-NO-CATCHUP"
EXPECTED_ORIGINS = {
    "https://github.com/rozkalnsandris/hermes-deals",
    "https://github.com/rozkalnsandris/hermes-deals.git",
    "git@github.com:rozkalnsandris/hermes-deals.git",
}


class StopCutover(RuntimeError):
    pass


def require(value: bool, reason: str) -> None:
    if not value:
        raise StopCutover(reason)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def json_bytes(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def command(argv: list[str], *, check: bool = True, as_audit: bool = False,
            audit_mutation: bool = False, timeout: int = 50,
            input_bytes: bytes | None = None) -> bytes:
    if as_audit:
        argv = ["/usr/sbin/runuser", "-u", "andris", "--",
                "/usr/bin/env", "-i", "HOME=/home/andris", "USER=andris",
                "LOGNAME=andris", "PATH=/usr/bin:/bin", "LANG=C.UTF-8",
                "GIT_OPTIONAL_LOCKS=" + ("1" if audit_mutation else "0"),
                *argv]
    p = subprocess.run(
        argv, input=input_bytes, stdin=subprocess.DEVNULL if input_bytes is None else None,
        capture_output=True, check=False, timeout=timeout,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "LANG": "C.UTF-8"},
    )
    if check:
        require(p.returncode == 0, "subcommand failed: " + Path(argv[0]).name)
        require(not p.stderr, "unexpected subcommand stderr: " + Path(argv[0]).name)
    return p.stdout


def git_read(*args: str) -> bytes:
    return command(["/usr/bin/git", "-C", str(APP_ROOT), *args], as_audit=True)


def git_str(*args: str) -> str:
    return git_read(*args).decode("utf-8").strip()


def validate_exact_python313_source(
    runner_bytes: bytes, manifest_bytes: bytes, runtime_lock_bytes: bytes,
) -> None:
    """Fail closed on an active-source/runtime mismatch before any LIVE write."""
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8", "strict"))
        runner = runner_bytes.decode("utf-8", "strict")
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StopCutover("registered EDEKA Python runtime contract invalid") from exc
    require(isinstance(manifest, dict) and isinstance(manifest.get("locks"), dict),
            "registered Python lock manifest invalid")
    require(set(manifest["locks"]) == {"runtime-py313.txt", "ci-py313.txt"},
            "registered Python runtime manifest not canonical")
    runtime = manifest["locks"]["runtime-py313.txt"]
    require(isinstance(runtime, dict) and runtime.get("python") == "3.13",
            "registered Python runtime not CPython 3.13")
    require(runtime.get("sha256") == sha256(runtime_lock_bytes),
            "registered Python 3.13 lock digest drift")
    for expected in (
        'PYTHON_BIN="python3.13"',
        'RUNTIME_LOCK_REL="backend/locks/runtime-py313.txt"',
        'manifest["locks"]["runtime-py313.txt"]',
        'identity["python"] != "3.13"',
        '"$python_line" == "3.13"',
    ):
        require(expected in runner, "registered EDEKA runner has old Python runtime contract")
    require("runtime-py311" not in runner and "Python 3.11" not in runner,
            "registered EDEKA runner still selects retired Python 3.11")


def verify_host_python313() -> None:
    """Read-only gate: interpreter needed by the reviewed EDEKA shadow runner."""
    probe = (
        "import platform,sys,venv,ensurepip;"
        "assert platform.python_implementation() == 'CPython';"
        "assert sys.version_info[:2] == (3,13);"
        "assert platform.machine() in ('aarch64','arm64');"
        "print('PY313_RUNTIME_PREFLIGHT_PASS')"
    )
    result = command([
        "/usr/sbin/runuser", "-u", "andris", "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE=1",
        "python3.13", "-c", probe,
    ])
    require(result == b"PY313_RUNTIME_PREFLIGHT_PASS\n",
            "EDEKA Python 3.13 host preflight receipt mismatch")


def check_source_and_get_assets(control_sha: str) -> tuple[ModuleType, bytes, str]:
    require(SHA40.fullmatch(control_sha) is not None, "control SHA invalid")
    require(APP_ROOT.is_dir() and not APP_ROOT.is_symlink(), "audit root unsafe")
    require((APP_ROOT / ".git").is_dir(), "audit Git metadata missing")
    require(git_str("remote", "get-url", "origin") in EXPECTED_ORIGINS, "wrong Git origin")
    require(git_str("branch", "--show-current") == "main", "audit branch drift")
    require(git_str("rev-parse", "HEAD") == OLD_SOURCE, "audit HEAD drift")
    require(git_read("status", "--porcelain=v1", "-z", "--untracked-files=all") == b"",
            "audit checkout dirty")
    for name in (APP_SOURCE, control_sha):
        require(git_str("rev-parse", "--verify", name + "^{commit}") == name,
                "reviewed commit not already staged")
    command(["/usr/bin/git", "-C", str(APP_ROOT),
             "merge-base", "--is-ancestor", OLD_SOURCE, APP_SOURCE], as_audit=True)
    command(["/usr/bin/git", "-C", str(APP_ROOT),
             "merge-base", "--is-ancestor", APP_SOURCE, control_sha], as_audit=True)
    # The reviewed APP_SOURCE must itself contain the canonical Python 3.13
    # runner, manifest and lock. A source pin change alone is not enough.
    validate_exact_python313_source(
        git_read("show", APP_SOURCE + ":" + RUNNER_REL),
        git_read("show", APP_SOURCE + ":" + RUNTIME_MANIFEST_REL),
        git_read("show", APP_SOURCE + ":" + RUNTIME_LOCK_REL),
    )
    path = Path(__file__)
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and not path.is_symlink(), "source executable unsafe")
    require(st.st_uid == 0 and st.st_gid == 0, "source executable not root-owned")
    require(stat.S_IMODE(st.st_mode) in (0o644, 0o755), "source mode drift")
    own_blob = git_str("rev-parse", control_sha + ":" + SELF_REL)
    require(own_blob == git_blob_sha(path.read_bytes()), "cutover script blob drift")

    helper_blob = git_str("rev-parse", control_sha + ":" + HELPER_REL)
    require(helper_blob == EXPECTED_HELPER_BLOB, "reviewed read-only helper drift")
    helper_raw = git_read("cat-file", "blob", helper_blob)
    require(git_blob_sha(helper_raw) == EXPECTED_HELPER_BLOB, "helper object drift")
    helper = ModuleType("reviewed_edeka_preflight")
    exec(compile(helper_raw, "reviewed_edeka_preflight", "exec"), helper.__dict__)

    dispatcher_blob = git_str("rev-parse", control_sha + ":" + DISPATCHER_REL)
    dispatcher = git_read("cat-file", "blob", dispatcher_blob)
    require(git_blob_sha(dispatcher) == dispatcher_blob, "dispatcher object drift")
    return helper, dispatcher, dispatcher_blob


def require_sunday_no_catchup_window(now: datetime, last_trigger: str) -> None:
    require(now.tzinfo is not None and now.utcoffset() is not None,
            "wall clock must be timezone-aware")
    local = now.astimezone(ZoneInfo("Europe/Berlin"))
    require(local.weekday() == 6 and time(2, 0) <= local.time() < time(23, 30),
            "Sunday no-catchup safe window not current")
    require(
        re.fullmatch(r"Sun \d{4}-\d\d-\d\d 00:10:00 (?:CET|CEST)",
                     last_trigger) is not None,
        "last Sunday timer trigger identity drift",
    )
    require(last_trigger.split(" ")[1] == local.date().isoformat(),
            "last Sunday timer trigger not from today")


def verify_persistent_stamp(local_now: datetime) -> int:
    """Read the actual systemd Persistent=true catch-up marker, never alter it."""
    st = PERSISTENT_STAMP.lstat()
    require(stat.S_ISREG(st.st_mode) and not PERSISTENT_STAMP.is_symlink(),
            "persistent stamp must be a regular non-symlink")
    require(st.st_uid == 0 and st.st_gid == 0
            and stat.S_IMODE(st.st_mode) == 0o644 and st.st_size == 0,
            "persistent stamp metadata drift")
    stamped = datetime.fromtimestamp(st.st_mtime, ZoneInfo("Europe/Berlin"))
    local = local_now.astimezone(ZoneInfo("Europe/Berlin"))
    require(stamped.date() == local.date() and stamped.weekday() == 6,
            "persistent stamp is not from today's Sunday invocation")
    require(stamped.hour == 0 and 10 <= stamped.minute <= 15,
            "persistent stamp is outside Sunday 00:10 accuracy window")
    return st.st_mtime_ns


def verify_status(*, sunday: bool) -> dict[str, str]:
    def props(unit: str) -> dict[str, str]:
        output = command(["/usr/bin/systemctl", "show", unit,
                          "-p", "Id", "-p", "UnitFileState", "-p", "ActiveState",
                          "-p", "Result", "-p", "ExecMainStatus",
                          "-p", "LastTriggerUSec", "-p", "NextElapseUSecRealtime",
                          "-p", "Persistent",
                          "--no-pager"])
        return dict(line.split("=", 1) for line in output.decode().splitlines()
                    if "=" in line)

    timer, service = props(TIMER), props(SERVICE)
    require(timer.get("Id") == TIMER and service.get("Id") == SERVICE,
            "systemd unit identity drift")
    require(timer.get("UnitFileState") == "enabled", "timer not enabled")
    require(timer.get("ActiveState") == "active", "timer not active")
    require(service.get("ActiveState") == "failed", "service failed-state evidence drift")
    require(service.get("ExecMainStatus") == "30", "service failure exit drift")
    require(not Path("/run/reboot-required").exists(), "reboot pending")
    if sunday:
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        require_sunday_no_catchup_window(now, timer.get("LastTriggerUSec", ""))
        require(timer.get("Persistent") in ("yes", "true"),
                "Persistent timer setting drift")
        verify_persistent_stamp(now)
        require(timer.get("NextElapseUSecRealtime", "").startswith("Sun "),
                "installed Sunday next elapse drift")
    return {"timer_active": "active", "service_failed": "true"}


def sudoers_bytes(control_sha: str, fp: str) -> bytes:
    prefix = "github-runner ALL=(root) NOPASSWD: " + str(DISPATCHER_PATH) + " "
    return (
        f"{prefix}activate {control_sha} {fp} source-refetch=authorized bounded-retries=authorized\n"
        f"{prefix}disable {control_sha} {fp} source-refetch=forbidden bounded-retries=forbidden\n"
        f"{prefix}rollback {control_sha} {fp} source-refetch=forbidden bounded-retries=forbidden\n"
    ).encode("utf-8")


def build_candidates(helper: ModuleType, control_sha: str, dispatcher: bytes,
                     dispatcher_blob: str) -> dict[Path, tuple[bytes, int]]:
    def read(path: Path, mode: int) -> bytes:
        return helper.read_root_regular(path, mode)

    service_old = read(UNIT_ROOT / SERVICE, 0o644)
    timer_old = read(UNIT_ROOT / TIMER, 0o644)
    alert_old = read(UNIT_ROOT / ALERT, 0o644)
    reg_old = read(REG_PATH, 0o600)
    ctl_old = read(CTL_PATH, 0o600)
    dispatcher_old = read(DISPATCHER_PATH, 0o755)
    sudoers_old = read(SUDOERS_PATH, 0o440)
    reg = helper.read_json(reg_old, helper.OLD_REGISTRATION_SHA256, "registration")
    ctl = helper.read_json(ctl_old, helper.OLD_CONTROL_CONFIG_SHA256, "control")
    preview = helper.build_readonly_proposal(
        service=service_old, timer=timer_old, alert=alert_old,
        registration=reg, control=ctl, dispatcher=dispatcher_old,
        sudoers=sudoers_old, reviewed_source_sha=APP_SOURCE,
    )
    require(preview["registration_fingerprint_candidate"] == EXPECTED_NEW_FP,
            "candidate registration fingerprint drift")
    require(preview["candidate_unit_sha256"][SERVICE] == EXPECTED_NEW_SERVICE_SHA256,
            "candidate service SHA drift")
    require(preview["candidate_unit_sha256"][TIMER] == EXPECTED_NEW_TIMER_SHA256,
            "candidate timer SHA drift")
    require(sudoers_old == sudoers_bytes(helper.OLD_CONTROL_SHA, helper.OLD_FINGERPRINT),
            "old sudoers semantics drift")

    old_pin = ("--expected-repo-sha " + OLD_SOURCE).encode("ascii")
    new_pin = ("--expected-repo-sha " + APP_SOURCE).encode("ascii")
    require(service_old.count(old_pin) == 1, "old service pin not unique")
    service_new = service_old.replace(old_pin, new_pin)
    require(sha256(service_new) == EXPECTED_NEW_SERVICE_SHA256,
            "new service digest drift")
    timer_new = helper.MONDAY_TIMER_BYTES
    require(sha256(timer_new) == EXPECTED_NEW_TIMER_SHA256, "new timer digest drift")
    reg_new = json.loads(reg_old)
    reg_new["registration_sha"] = APP_SOURCE
    reg_new["schedule"]["on_calendar"] = helper.NEW_CALENDAR
    reg_new["unit_sha256"][SERVICE] = sha256(service_new)
    reg_new["unit_sha256"][TIMER] = sha256(timer_new)
    reg_new["registration_fingerprint_sha256"] = EXPECTED_NEW_FP
    reg_bytes = json_bytes(reg_new)
    require(sha256(reg_bytes) == EXPECTED_NEW_REG_SHA256, "new registration digest drift")

    ctl_new = json.loads(ctl_old)
    ctl_new["control_sha"] = control_sha
    ctl_new["registration_sha"] = APP_SOURCE
    ctl_new["registration_fingerprint_sha256"] = EXPECTED_NEW_FP
    ctl_new["dispatcher_blob"] = dispatcher_blob
    ctl_new["dispatcher_sha256"] = sha256(dispatcher)
    ctl_bytes = json_bytes(ctl_new)
    sudoers_new = sudoers_bytes(control_sha, EXPECTED_NEW_FP)
    assert b"NOPASSWD:" in sudoers_new
    return {
        UNIT_ROOT / SERVICE: (service_new, 0o644),
        UNIT_ROOT / TIMER: (timer_new, 0o644),
        REG_PATH: (reg_bytes, 0o600),
        DISPATCHER_PATH: (dispatcher, 0o755),
        CTL_PATH: (ctl_bytes, 0o600),
        SUDOERS_PATH: (sudoers_new, 0o440),
    }


def write_once(path: Path, payload: bytes, mode: int) -> None:
    require(path.parent.is_dir() and not path.parent.is_symlink(),
            "unsafe installed-file parent")
    fd, temp_path = tempfile.mkstemp(prefix="." + path.name + ".monday-", dir=path.parent)
    # Temp files are intentionally preserved after any error for evidence.
    with os.fdopen(fd, "wb") as out:
        out.write(payload)
        out.flush()
        os.fchown(out.fileno(), 0, 0)
        os.fchmod(out.fileno(), mode)
        os.fsync(out.fileno())
    os.replace(temp_path, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def make_plan(control_sha: str) -> tuple[dict[Path, tuple[bytes, int]], dict]:
    require(os.geteuid() == 0, "root required to inspect current exact registration")
    helper, dispatcher, dispatcher_blob = check_source_and_get_assets(control_sha)
    verify_host_python313()
    helper.readonly_host_attestation()
    verify_status(sunday=True)
    result = build_candidates(helper, control_sha, dispatcher, dispatcher_blob)
    return result, {
        "schema_version": 1,
        "result": "PREFLIGHT_ONLY",
        "host": "rpi5",
        "issue": 1183,
        "old_source": OLD_SOURCE,
        "reviewed_app_source": APP_SOURCE,
        "reviewed_control_source": control_sha,
        "new_registration_fingerprint": EXPECTED_NEW_FP,
        "candidate_file_sha256": {
            p.name: sha256(raw) for p, (raw, _) in sorted(
                result.items(), key=lambda x: str(x[0])
            )
        },
        "persistent_catchup_policy": "FORBID",
        "live_mutation_authorized": False,
        "live_mutation_performed": False,
    }


def apply_once(control_sha: str, token: str) -> None:
    require(token == LIVE_TOKEN, "one-shot LIVE intent flag missing")
    require(os.geteuid() == 0, "root required")
    # Read-only checks before opening even the lock file.
    candidate, plan = make_plan(control_sha)
    stamp_mtime_ns = verify_persistent_stamp(
        datetime.now(ZoneInfo("Europe/Berlin")),
    )
    require(LOCK.parent.is_dir() and not LOCK.parent.is_symlink(), "lock directory unsafe")
    require(not LOCK.is_symlink(), "lock path unsafe")
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    # This is the first host mutation when the lock file did not exist.
    try:
        lock_stat = os.fstat(fd)
        require(stat.S_ISREG(lock_stat.st_mode) and lock_stat.st_uid == 0
                and lock_stat.st_gid == 0
                and stat.S_IMODE(lock_stat.st_mode) == 0o600,
                "cutover lock metadata drift")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Revalidate under the exclusive cutover lock before first service mutation.
        latest, refreshed = make_plan(control_sha)
        require(refreshed == plan and latest == candidate, "preflight drift under lock")
        require(verify_persistent_stamp(
            datetime.now(ZoneInfo("Europe/Berlin"))
        ) == stamp_mtime_ns, "Persistent timer stamp drift under lock")

        command(["/usr/bin/systemctl", "stop", TIMER])
        state = command(["/usr/bin/systemctl", "show", TIMER,
                         "-p", "ActiveState", "--no-pager"]).decode().strip()
        require(state == "ActiveState=inactive", "timer did not stop")

        # All objects were staged before apply; no implicit network, fetch or reset.
        command(["/usr/bin/git", "-C", str(APP_ROOT), "-c",
                 "core.hooksPath=/dev/null", "merge", "--ff-only", APP_SOURCE],
                as_audit=True, audit_mutation=True)
        require(git_str("rev-parse", "HEAD") == APP_SOURCE, "audit HEAD post-merge drift")
        require(git_read("status", "--porcelain=v1", "-z", "--untracked-files=all") == b"",
                "audit checkout post-merge dirty")
        for path, (payload, mode) in candidate.items():
            write_once(path, payload, mode)
            require(sha256(path.read_bytes()) == sha256(payload),
                    "post-write file content mismatch")
        command(["/usr/bin/systemctl", "daemon-reload"])
        # A catch-up from Persistent=true is forbidden. Do not start after
        # Sunday's previously observed trigger and before Monday window lapses.
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        require_sunday_no_catchup_window(now, command([
            "/usr/bin/systemctl", "show", TIMER,
            "-p", "LastTriggerUSec", "--no-pager"
        ]).decode().strip().partition("=")[2])
        require(verify_persistent_stamp(now) == stamp_mtime_ns,
                "Persistent timer stamp changed during cutover")
        command(["/usr/bin/systemctl", "start", TIMER])

        status = command(["/usr/bin/systemctl", "show", TIMER,
                          "-p", "ActiveState", "-p", "UnitFileState",
                          "-p", "NextElapseUSecRealtime", "--no-pager"]).decode()
        require("ActiveState=active" in status and "UnitFileState=enabled" in status,
                "timer failed post-cutover verification")
        require("NextElapseUSecRealtime=Mon " in status, "Monday next elapse missing")
        require(verify_persistent_stamp(
            datetime.now(ZoneInfo("Europe/Berlin"))
        ) == stamp_mtime_ns, "unexpected Persistent timer catch-up trigger")
        require(git_str("rev-parse", "HEAD") == APP_SOURCE, "final audit HEAD drift")
        for path, (payload, mode) in candidate.items():
            require(sha256(helper_read_root_regular(path, mode)) == sha256(payload),
                    "final installed bytes/metadata drift")
        print(json.dumps({
            **plan, "result": "CUTOVER_SOURCE_AND_TIMER_APPLIED",
            "live_mutation_authorized": True,
            "live_mutation_performed": True,
            "post_timer_enabled": True, "post_timer_active": True,
            "next_calendar": "Mon *-*-* 00:10:00 Europe/Berlin",
            "manual_source_collection_performed": False,
            "production_database_write_performed": False,
            "reboot_performed": False,
        }, sort_keys=True))
    finally:
        os.close(fd)


def helper_read_root_regular(path: Path, mode: int) -> bytes:
    st = path.lstat()
    require(stat.S_ISREG(st.st_mode) and not path.is_symlink(),
            "final file type mismatch")
    require(st.st_uid == 0 and st.st_gid == 0 and stat.S_IMODE(st.st_mode) == mode,
            "final file metadata mismatch")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EDEKA Monday exact-SHA forward cutover")
    parser.add_argument("--phase", choices=("preflight", "apply"), required=True)
    parser.add_argument("--control-sha", required=True)
    parser.add_argument("--live-intent", default="FORBIDDEN")
    args = parser.parse_args(argv)
    try:
        require(os.geteuid() == 0, "root required")
        if args.phase == "preflight":
            require(args.live_intent == "FORBIDDEN", "preflight must exclude LIVE intent")
            _, plan = make_plan(args.control_sha)
            print(json.dumps(plan, sort_keys=True))
        else:
            apply_once(args.control_sha, args.live_intent)
    except (StopCutover, OSError, ValueError, KeyError, UnicodeError,
            subprocess.SubprocessError, BlockingIOError) as exc:
        print(json.dumps({
            "schema_version": 1, "result": "STOP",
            "error_type": type(exc).__name__,
            "no_automatic_retry_rollback_or_cleanup": True,
            "read_only_reconciliation_required": True,
        }, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
