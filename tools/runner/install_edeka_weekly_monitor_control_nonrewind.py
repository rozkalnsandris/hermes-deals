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
import tempfile
from typing import Any, Mapping

SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
CONTROL = "edeka-weekly-monitor-control-v1"
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_REGISTRATION_SHA = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
EXPECTED_REGISTRATION_FINGERPRINT = "f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb"
REGISTRATION_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-unit-registration.json")
CONTROL_CONFIG = Path("/etc/hermes-deals-audits.d/edeka-weekly-monitor-control.json")
DISPATCHER_REL = "tools/runner/edeka_weekly_monitor_control.py"
INSTALLER_REL = "tools/runner/install_edeka_weekly_monitor_control_nonrewind.py"
AUTHOR_REL = "tools/github_edeka_weekly_monitor_control.py"
WORKFLOW_REL = ".github/workflows/hermes-edeka-weekly-monitor-control.yml"
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-edeka-weekly-monitor-control")
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


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


def load_registration_config() -> dict[str, Any]:
    require(regular_root_file(REGISTRATION_CONFIG, 0o600), "EDEKA monitor registration config missing or unsafe")
    try:
        config = json.loads(REGISTRATION_CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("EDEKA monitor registration config JSON invalid") from exc
    require(isinstance(config, dict), "EDEKA monitor registration config root invalid")
    require(config.get("registration_sha") == EXPECTED_REGISTRATION_SHA, "EDEKA monitor registration SHA drift")
    require(config.get("registration_fingerprint_sha256") == EXPECTED_REGISTRATION_FINGERPRINT, "EDEKA monitor registration fingerprint drift")
    core = {key: value for key, value in config.items() if key != "registration_fingerprint_sha256"}
    require(sha256_bytes(canonical_bytes(core)) == EXPECTED_REGISTRATION_FINGERPRINT, "EDEKA monitor registration fingerprint recomputation mismatch")
    return config


def validate_source(control_sha: str) -> dict[str, str]:
    require(SHA40_RE.fullmatch(control_sha) is not None, "control SHA invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository missing or unsafe")
    require((SOURCE_REPO / ".git").exists(), "dedicated EDEKA audit repository is not a Git checkout")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == EXPECTED_REGISTRATION_SHA, "dedicated EDEKA audit HEAD must remain pinned to registration SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated EDEKA audit repository is not clean")
    git("show-ref", "--verify", "--quiet", "refs/remotes/origin/main")
    require(git_text("rev-parse", "refs/remotes/origin/main") == control_sha, "control SHA is not exact fetched origin/main")
    require(git("merge-base", "--is-ancestor", EXPECTED_REGISTRATION_SHA, control_sha, check=False).returncode == 0, "control SHA does not descend from registered monitor source")

    blobs: dict[str, str] = {}
    for path in (DISPATCHER_REL, INSTALLER_REL, AUTHOR_REL, WORKFLOW_REL):
        blob = git_text("rev-parse", f"{control_sha}:{path}")
        require(re.fullmatch(r"[0-9a-f]{40}", blob) is not None, f"control source blob invalid: {path}")
        blobs[path] = blob

    running = Path(__file__).read_bytes()
    require(git_blob_sha(running) == blobs[INSTALLER_REL], "running installer bytes differ from control commit")
    return blobs


def cat_blob(blob: str) -> bytes:
    payload = git("cat-file", "blob", blob).stdout
    require(git_blob_sha(payload) == blob, "Git blob payload identity drift")
    return payload


def write_exclusive_or_identical(path: Path, payload: bytes, mode: int) -> bool:
    if path.exists() or path.is_symlink():
        require(regular_root_file(path, mode), f"existing root registration path unsafe: {path}")
        require(path.read_bytes() == payload, f"existing root registration content drift: {path}")
        return False
    require(path.parent.is_dir() and not path.parent.is_symlink(), f"root registration parent missing or unsafe: {path.parent}")
    parent_info = path.parent.stat()
    require(parent_info.st_uid == 0 and parent_info.st_gid == 0, f"root registration parent ownership drift: {path.parent}")
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


def build_sudoers(control_sha: str, fingerprint: str) -> bytes:
    sudo_tag = "".join(("NO", "PASS", "WD", ":"))
    base = f"github-runner ALL=(root) {sudo_tag} {DISPATCH_DST}"
    lines = [
        f"{base} activate {control_sha} {fingerprint} source-refetch=authorized bounded-retries=authorized",
        f"{base} disable {control_sha} {fingerprint} source-refetch=forbidden bounded-retries=forbidden",
        f"{base} rollback {control_sha} {fingerprint} source-refetch=forbidden bounded-retries=forbidden",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def validate_sudoers(payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix="edeka-monitor-control-sudoers-", dir="/run")
    path = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o440)
        result = run(["/usr/sbin/visudo", "-cf", str(path)], check=False)
        require(result.returncode == 0, "generated sudoers policy failed visudo validation")
    finally:
        path.unlink(missing_ok=True)


def build_control_config(control_sha: str, blobs: Mapping[str, str], dispatcher_bytes: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "control": CONTROL,
        "issue_number": EXPECTED_ISSUE_NUMBER,
        "control_sha": control_sha,
        "dispatcher_blob": blobs[DISPATCHER_REL],
        "dispatcher_sha256": sha256_bytes(dispatcher_bytes),
        "registration_sha": EXPECTED_REGISTRATION_SHA,
        "registration_fingerprint_sha256": EXPECTED_REGISTRATION_FINGERPRINT,
        "root_registration_only": True,
        "systemd_change_performed": False,
        "source_refetch_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
    }


def register(control_sha: str, fingerprint: str) -> dict[str, Any]:
    require(os.geteuid() == 0, "control registration must run as root")
    require(fingerprint == EXPECTED_REGISTRATION_FINGERPRINT, "registration fingerprint mismatch")
    load_registration_config()
    blobs = validate_source(control_sha)
    dispatcher_bytes = cat_blob(blobs[DISPATCHER_REL])
    require(dispatcher_bytes.startswith(b"#!/usr/bin/env python3\n"), "dispatcher shebang drift")

    sudoers_bytes = build_sudoers(control_sha, fingerprint)
    validate_sudoers(sudoers_bytes)
    control_config = canonical_bytes(build_control_config(control_sha, blobs, dispatcher_bytes))

    dispatcher_changed = write_exclusive_or_identical(DISPATCH_DST, dispatcher_bytes, 0o755)
    config_changed = write_exclusive_or_identical(CONTROL_CONFIG, control_config, 0o600)
    sudoers_changed = write_exclusive_or_identical(SUDOERS_DST, sudoers_bytes, 0o440)

    return {
        "result": "PASS",
        "control": CONTROL,
        "control_sha": control_sha,
        "registration_sha": EXPECTED_REGISTRATION_SHA,
        "registration_fingerprint_sha256": EXPECTED_REGISTRATION_FINGERPRINT,
        "dispatcher_blob": blobs[DISPATCHER_REL],
        "dispatcher_sha256": sha256_bytes(dispatcher_bytes),
        "dispatcher_changed": dispatcher_changed,
        "control_config_changed": config_changed,
        "sudoers_changed": sudoers_changed,
        "root_host_mutation_performed": dispatcher_changed or config_changed or sudoers_changed,
        "systemd_change_performed": False,
        "timer_enable_performed": False,
        "timer_start_performed": False,
        "source_refetch_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register the EDEKA weekly monitor owner-control dispatcher without activating systemd.")
    parser.add_argument("--control-sha", required=True)
    parser.add_argument("--registration-fingerprint", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = register(args.control_sha, args.registration_fingerprint)
    except (OSError, UnicodeError, ValueError, RegistrationError, subprocess.SubprocessError) as exc:
        print(json.dumps({"result": "BLOCKED", "control": CONTROL, "error_type": type(exc).__name__}, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    print("EDEKA_WEEKLY_MONITOR_CONTROL_REGISTRATION=PASS")
    print(f"ROOT_HOST_MUTATION={'true' if receipt['root_host_mutation_performed'] else 'false'}")
    print("SYSTEMD_CHANGE=false")
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
