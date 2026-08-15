#!/usr/bin/env python3
from __future__ import annotations

import argparse
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
from typing import Any


SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
INSTALLER_REL = "tools/runner/install_edeka_weekly_monitor_control_nonrewind.py"
DISPATCHER_REL = "tools/runner/edeka_weekly_monitor_control.py"
UNIT_INSTALLER_REL = "tools/runner/install_edeka_weekly_monitor_units_nonactivating.py"
EXPECTED_DISPATCHER_BLOB = "503890a63c4e52dd60aac5f8b502c6e256869c8c"
EXPECTED_UNIT_INSTALLER_BLOB = "91ddc076ec6407b567a3ae3300bef0e8a7adfca5"
EXPECTED_BRIDGE_PR = 673
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-edeka-weekly-monitor-control")
UNIT_REGISTRATION_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


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


def git_blob_bytes(commit: str, path: str) -> bytes:
    blob = git_text("rev-parse", f"{commit}:{path}")
    result = git("cat-file", "blob", blob)
    payload = bytes(result.stdout)
    require(payload, f"Git blob is empty: {path}")
    return payload


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
    require(git_text("rev-parse", "refs/remotes/origin/main") == registration_sha, "registration SHA is not exact origin/main")
    expected = {DISPATCHER_REL: EXPECTED_DISPATCHER_BLOB, UNIT_INSTALLER_REL: EXPECTED_UNIT_INSTALLER_BLOB}
    for path, oid in expected.items():
        require(git_text("rev-parse", f"{registration_sha}:{path}") == oid, f"reviewed Git blob mismatch: {path}")
    installer_blob = git_text("rev-parse", f"{registration_sha}:{INSTALLER_REL}")
    require(git_text("hash-object", str(Path(__file__).resolve())) == installer_blob, "running installer bytes differ from the registration commit")
    return {**expected, INSTALLER_REL: installer_blob}


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


def regular_root_file(path: Path, mode: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode


def write_exclusive_or_identical(path: Path, payload: bytes, mode: int) -> bool:
    if path.exists() or path.is_symlink():
        require(regular_root_file(path, mode), f"existing registration path metadata drift: {path}")
        require(path.read_bytes() == payload, f"existing registration content drift: {path}")
        return False
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"registration parent is missing or unsafe: {path.parent}")
    parent_info = path.parent.stat()
    require(parent_info.st_uid == 0 and parent_info.st_gid == 0, f"registration parent owner mismatch: {path.parent}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.edeka-monitor-control-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchown(fd, 0, 0)
        os.fchmod(fd, mode)
        os.close(fd)
        fd = -1
        os.link(temp, path, follow_symlinks=False)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)
    return True


def sudo_version_at_least_1_9_10() -> str:
    result = run(["/usr/bin/sudo", "-V"])
    line = result.stdout.splitlines()[0] if result.stdout else ""
    match = re.fullmatch(r"Sudo version ([0-9]+)\.([0-9]+)\.([0-9]+)(?:.*)?", line)
    require(match is not None, "unable to parse host Sudo version")
    version = tuple(int(match.group(i)) for i in (1, 2, 3))
    require(version >= (1, 9, 10), "host Sudo is older than 1.9.10")
    return line


def runner_not_in_docker_group() -> None:
    try:
        user = pwd.getpwnam(RUNNER_USER)
    except KeyError as exc:
        raise RegistrationError("github-runner account is unavailable") from exc
    groups = {grp.getgrgid(gid).gr_name for gid in os.getgrouplist(RUNNER_USER, user.pw_gid)}
    require("docker" not in groups, "github-runner must not belong to Docker group")


def load_verified_dispatcher_source():
    path = SOURCE_REPO / DISPATCHER_REL
    require(git_text("hash-object", str(path)) == EXPECTED_DISPATCHER_BLOB, "working-tree dispatcher bytes drift")
    spec = importlib.util.spec_from_file_location("edeka_weekly_monitor_control_registration_source", path)
    require(spec is not None and spec.loader is not None, "unable to load reviewed dispatcher source")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_registration_identity() -> tuple[str, str]:
    require(regular_root_file(UNIT_REGISTRATION_CONFIG, 0o600), "EDEKA unit registration config missing or unsafe")
    try:
        raw = json.loads(UNIT_REGISTRATION_CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("EDEKA unit registration config JSON invalid") from exc
    require(isinstance(raw, dict), "EDEKA unit registration config root invalid")
    sha = str(raw.get("registration_sha") or "")
    fingerprint = str(raw.get("registration_fingerprint_sha256") or "")
    require(SHA40_RE.fullmatch(sha) is not None, "registered SHA invalid")
    require(SHA256_RE.fullmatch(fingerprint) is not None, "registration fingerprint invalid")
    return sha, fingerprint


def build_sudoers() -> bytes:
    regex = (
        r"^(activate [0-9a-f]{40} [0-9a-f]{64} source-refetch-authorized bounded-retries-authorized"
        r"|disable [0-9a-f]{40} [0-9a-f]{64}"
        r"|rollback [0-9a-f]{40} [0-9a-f]{64})$"
    )
    return (
        f"Cmnd_Alias HERMES_DEALS_EDEKA_WEEKLY_MONITOR_CONTROL = {DISPATCH_DST} {regex}\n"
        f"{RUNNER_USER} ALL=(root) NOPASSWD: HERMES_DEALS_EDEKA_WEEKLY_MONITOR_CONTROL\n"
    ).encode("utf-8")


def install_registration(args: argparse.Namespace) -> dict[str, Any]:
    require(os.geteuid() == 0, "control registration must run as root")
    blobs = validate_source_repo(args.registration_sha)
    runner_not_in_docker_group()
    sudo_version = sudo_version_at_least_1_9_10()
    registered_sha, fingerprint = current_registration_identity()
    require(registered_sha == args.registration_sha, "unit registration SHA is not exact current main")
    dispatcher_module = load_verified_dispatcher_source()
    config = dispatcher_module.load_registration(registered_sha, fingerprint)
    units = dispatcher_module.validate_installed_units(config)
    dispatcher_module.preflight(config, units)
    require(not dispatcher_module.timer_is_live_enabled(), "timer must be disabled before control trust registration")
    require(not dispatcher_module.timer_is_active(), "timer must be inactive before control trust registration")
    require(not dispatcher_module.service_is_active(), "monitor service must be inactive before control trust registration")

    dispatcher = git_blob_bytes(args.registration_sha, DISPATCHER_REL)
    changed = write_exclusive_or_identical(DISPATCH_DST, dispatcher, 0o755)
    sudoers = build_sudoers()
    with tempfile.TemporaryDirectory(prefix="edeka-monitor-control-sudoers-") as temp_name:
        temp = Path(temp_name) / "sudoers"
        temp.write_bytes(sudoers)
        os.chmod(temp, 0o440)
        run(["/usr/sbin/visudo", "-cf", str(temp)])
    changed |= write_exclusive_or_identical(SUDOERS_DST, sudoers, 0o440)
    run(["/usr/sbin/visudo", "-cf", str(SUDOERS_DST)])

    valid = (
        [str(DISPATCH_DST), "activate", registered_sha, fingerprint, "source-refetch-authorized", "bounded-retries-authorized"],
        [str(DISPATCH_DST), "disable", registered_sha, fingerprint],
        [str(DISPATCH_DST), "rollback", registered_sha, fingerprint],
    )
    for argv in valid:
        probe = run(["/usr/bin/sudo", "-n", "-l", "-U", RUNNER_USER, "--", *argv], check=False)
        require(probe.returncode == 0, f"github-runner sudo policy missing for {argv[1]}")
    malformed = (
        [str(DISPATCH_DST), "activate", registered_sha, fingerprint],
        [str(DISPATCH_DST), "activate", registered_sha, fingerprint, "source-refetch-authorized", "bounded-retries-authorized", "extra"],
        [str(DISPATCH_DST), "unknown", registered_sha, fingerprint],
        [str(DISPATCH_DST), "disable", registered_sha],
    )
    for argv in malformed:
        probe = run(["/usr/bin/sudo", "-n", "-l", "-U", RUNNER_USER, "--", *argv], check=False)
        require(probe.returncode != 0, "github-runner sudo policy accepts malformed EDEKA monitor arguments")

    return {
        "result": "PASS" if changed else "NO_OP_IDENTICAL",
        "registration_sha": registered_sha,
        "registration_fingerprint": fingerprint,
        "bridge_pr": EXPECTED_BRIDGE_PR,
        "dispatcher_blob": blobs[DISPATCHER_REL],
        "unit_registration_installer_blob": blobs[UNIT_INSTALLER_REL],
        "sudo_version": sudo_version,
        "root_registration_performed": changed,
        "systemd_change_performed": False,
        "timer_activation_performed": False,
        "source_refetch_authorized": False,
        "bounded_retry_authorized": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register the non-activating EDEKA weekly-monitor owner-control trust root.")
    parser.add_argument("--registration-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = install_registration(args)
    except (OSError, UnicodeError, ValueError, RegistrationError, subprocess.SubprocessError) as exc:
        print(json.dumps({"result": "BLOCKED", "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    print(f"EDEKA_WEEKLY_MONITOR_CONTROL_REGISTRATION={result['result']}")
    print(f"REGISTRATION_SHA={result['registration_sha']}")
    print(f"REGISTRATION_FINGERPRINT={result['registration_fingerprint']}")
    print("SYSTEMD_CHANGE=false")
    print("TIMER_ACTIVATION=false")
    print("SOURCE_REFETCH=false")
    print("BOUNDED_RETRIES=false")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_WRITE=false")
    print("PRODUCTION_PUBLISH=false")
    print("PRODUCTION_DEPLOY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
