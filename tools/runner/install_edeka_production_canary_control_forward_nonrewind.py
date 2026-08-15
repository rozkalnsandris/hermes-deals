#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")
AUDIT_USER = "andris"
WRAPPER_REL = "tools/runner/install_edeka_production_canary_control_forward_nonrewind.py"
INSTALLER_REL = "tools/runner/install_edeka_production_canary_control_nonrewind.py"
DISPATCHER_REL = "tools/runner/edeka_production_canary_control.py"
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-edeka-production-canary-control")

EXPECTED_INSTALLER_BLOB = "4285d3b1bdbaeddfc2d6698a96cb91c40f7d7946"
TARGET_DISPATCHER_BLOB = "95339e076907e43eb2307fce66f4768a60ef2296"
PREDECESSOR_DISPATCHER_BLOB = "f4c54c91ded3edcd631f3e83f37a54229dfb2413"
SHA40_RE = re.compile(r"[0-9a-f]{40}")

SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
}


class ForwardUpgradeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ForwardUpgradeError(message)


def git_blob_oid(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def run(argv: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env=SAFE_ENV,
    )
    if check:
        require(result.returncode == 0, f"command failed: {Path(argv[0]).name}")
    return result


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    argv = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        "HOME=/home/andris", "USER=andris", "LOGNAME=andris",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(SOURCE_REPO), *args,
    ]
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=90,
    )
    if check:
        require(result.returncode == 0, f"audit Git command failed: {args[0]}")
        require(not result.stderr, f"audit Git command emitted stderr: {args[0]}")
    return result


def git_text(*args: str) -> str:
    return git(*args).stdout.decode("utf-8", "strict").strip()


def git_blob_bytes(blob_oid: str) -> bytes:
    require(SHA40_RE.fullmatch(blob_oid) is not None, "Git blob identity invalid")
    payload = git("cat-file", "blob", blob_oid).stdout
    require(payload, "Git blob is empty")
    require(git_blob_oid(payload) == blob_oid, "Git blob bytes do not match requested identity")
    return payload


def classify_dispatcher_blob(current_blob: str | None) -> str:
    if current_blob is None:
        return "absent"
    require(SHA40_RE.fullmatch(current_blob) is not None, "installed dispatcher blob identity invalid")
    if current_blob == TARGET_DISPATCHER_BLOB:
        return "identical"
    require(
        current_blob == PREDECESSOR_DISPATCHER_BLOB,
        "installed dispatcher is neither exact target nor approved predecessor",
    )
    return "forward_upgrade"


def validate_source_repo(target_sha: str) -> None:
    require(os.geteuid() == 0, "forward registration must run as root")
    require(SHA40_RE.fullmatch(target_sha) is not None, "target SHA invalid")
    require(SOURCE_REPO.is_dir() and not SOURCE_REPO.is_symlink(), "dedicated EDEKA audit repository missing or unsafe")
    require((SOURCE_REPO / ".git").is_dir() and not (SOURCE_REPO / ".git").is_symlink(), "dedicated EDEKA audit Git metadata unsafe")
    require(Path(__file__).resolve() == (SOURCE_REPO / WRAPPER_REL).resolve(), "forward wrapper must execute from dedicated EDEKA audit checkout")
    require(not (SOURCE_REPO / ".git/index.lock").exists(), "audit Git index lock exists")
    require(git_text("branch", "--show-current") == "main", "dedicated EDEKA audit repository is not on main")
    require(git_text("rev-parse", "HEAD") == target_sha, "dedicated EDEKA audit HEAD differs from target SHA")
    require(git_text("rev-parse", "refs/remotes/origin/main") == target_sha, "origin/main differs from target SHA")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "dedicated EDEKA audit repository is not clean")
    origin = git_text("remote", "get-url", "origin")
    require(origin in {
        "https://github.com/rozkalnsandris/hermes-deals",
        "https://github.com/rozkalnsandris/hermes-deals.git",
        "git@github.com:rozkalnsandris/hermes-deals.git",
    }, "dedicated EDEKA audit origin is not allowlisted")

    require(git_text("rev-parse", f"{target_sha}:{INSTALLER_REL}") == EXPECTED_INSTALLER_BLOB, "registration installer blob drift")
    require(git_text("rev-parse", f"{target_sha}:{DISPATCHER_REL}") == TARGET_DISPATCHER_BLOB, "target dispatcher blob drift")
    wrapper_oid = git_text("rev-parse", f"{target_sha}:{WRAPPER_REL}")
    require(git_text("hash-object", str(Path(__file__).resolve())) == wrapper_oid, "running forward wrapper bytes differ from target commit")


def dispatcher_state() -> tuple[str, tuple[int, int, int, int, int] | None]:
    if not DISPATCH_DST.exists() and not DISPATCH_DST.is_symlink():
        return classify_dispatcher_blob(None), None

    require(DISPATCH_DST.is_file() and not DISPATCH_DST.is_symlink(), "existing dispatcher path unsafe")
    info = DISPATCH_DST.stat()
    require(
        info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755,
        "existing dispatcher metadata drift",
    )
    payload = DISPATCH_DST.read_bytes()
    state = classify_dispatcher_blob(git_blob_oid(payload))
    fingerprint = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return state, fingerprint


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def forward_upgrade_dispatcher() -> str:
    state, before = dispatcher_state()
    if state in {"absent", "identical"}:
        return state

    require(before is not None, "approved predecessor fingerprint missing")
    target_payload = git_blob_bytes(TARGET_DISPATCHER_BLOB)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{DISPATCH_DST.name}.forward-",
        dir=DISPATCH_DST.parent,
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(target_payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o755)
        os.close(fd)
        fd = -1

        state_now, before_now = dispatcher_state()
        require(state_now == "forward_upgrade", "dispatcher changed before atomic forward replacement")
        require(before_now == before, "dispatcher metadata changed before atomic forward replacement")

        os.replace(temp, DISPATCH_DST)
        fsync_directory(DISPATCH_DST.parent)
        temp = None

        state_after, _ = dispatcher_state()
        require(state_after == "identical", "dispatcher forward replacement verification failed")
        return "forward_upgrade"
    finally:
        if fd >= 0:
            os.close(fd)
        if temp is not None:
            temp.unlink(missing_ok=True)


def run_registration_installer(target_sha: str) -> None:
    installer = SOURCE_REPO / INSTALLER_REL
    require(installer.is_file() and not installer.is_symlink(), "registration installer path unsafe")
    result = run(
        ["/usr/bin/python3", str(installer), "--registration-sha", target_sha],
        check=False,
        timeout=240,
    )
    stdout = result.stdout.decode("utf-8", "replace")
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    require(result.returncode == 0, "registration installer failed after dispatcher forward preparation")
    require(not result.stderr, "registration installer emitted stderr")


def install_forward_registration(target_sha: str) -> str:
    validate_source_repo(target_sha)
    state = forward_upgrade_dispatcher()
    run_registration_installer(target_sha)
    return state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Perform one checksum-bound EDEKA dispatcher forward upgrade, then run the existing non-rewind root registration installer."
    )
    parser.add_argument("--registration-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state = install_forward_registration(args.registration_sha)
    except (OSError, ValueError, ForwardUpgradeError, subprocess.SubprocessError) as exc:
        message = str(exc)
        if len(message) > 240:
            message = message[:240]
        print(f"ERROR|{type(exc).__name__}|{message}")
        return 2

    print(f"EDEKA_DISPATCHER_FORWARD_STATE={state}")
    print("CANARY_OPERATION=false")
    print("PRODUCTION_DATABASE_WRITE=false")
    print("REVIEW_WRITE=false")
    print("PRODUCTION_PUBLISH=false")
    print("SOURCE_REFETCH=false")
    print("SCHEDULER_SYSTEMD_CHANGE=false")
    print("PRODUCTION_DEPLOY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
