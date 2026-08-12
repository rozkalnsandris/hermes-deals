#!/usr/bin/env python3
from __future__ import annotations

import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = Path("/home/andris/hermes-deals-audit-source")
AUDIT_USER = "andris"
AUDIT_HOME = "/home/andris"
RUNNER_USER = "github-runner"
AUDIT = "aldi-gate-d3-recovery-inventory"
EXPECTED_TARGET_SHA = "530a6b6d2b31f635f182788ccace01003b1cbc7d"
INVENTORY_PATH = "tools/aldi_gate_d3_recovery_inventory.py"
DISPATCHER_PATH = "tools/runner/aldi_gate_d3_recovery_inventory_dispatch.py"
EXPECTED_INVENTORY_BLOB = "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
EXPECTED_DISPATCHER_BLOB = "70c56f6ff883415a18949c6298be4affe8f8ac0d"
AUDITS_ROOT = Path("/usr/local/libexec/hermes-deals-audits")
INSTALL_ROOT = AUDITS_ROOT / AUDIT
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-aldi-gate-d3-recovery-inventory")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d3-recovery-inventory.json")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-aldi-gate-d3-recovery-inventory")
RUNNER_SERVICE = "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"


class RegistrationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistrationError(message)


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_snapshot() -> tuple[str, int, int, str]:
    index = REPO / ".git/index"
    require(index.is_file() and not index.is_symlink(), "audit repo index missing or unsafe")
    require(not (REPO / ".git/index.lock").exists(), "audit repo index locked")
    info = index.stat()
    owner = f"{pwd.getpwuid(info.st_uid).pw_name}:{grp.getgrgid(info.st_gid).gr_name}"
    require(owner == "andris:andris", "audit repo index owner mismatch")
    return owner, stat.S_IMODE(info.st_mode), info.st_size, sha_file(index)


def audit_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    command = [
        "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
        "/usr/bin/env", "-i",
        f"HOME={AUDIT_HOME}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
        "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0",
        "/usr/bin/git", "-C", str(REPO), *args,
    ]
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if check:
        require(completed.returncode == 0, f"audit git failed: {args[0]}")
        require(not completed.stderr, f"audit git emitted stderr: {args[0]}")
    return completed


def validate_source_repo(target_sha: str) -> tuple[tuple[str, int, int, str], str]:
    require(target_sha == EXPECTED_TARGET_SHA, "target SHA is not the reviewed PR #281 merge SHA")
    before = index_snapshot()
    require(audit_git("branch", "--show-current").stdout.decode().strip() == "main", "audit repo branch mismatch")
    head = audit_git("rev-parse", "HEAD").stdout.decode().strip()
    require(len(head) == 40, "audit repo HEAD invalid")
    require(audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo dirty")

    target = audit_git("rev-parse", "--verify", f"{target_sha}^{{commit}}").stdout.decode().strip()
    require(target == target_sha, "reviewed target commit object unavailable")
    ancestry = audit_git("merge-base", "--is-ancestor", target_sha, head, check=False)
    require(ancestry.returncode == 0, "reviewed target is not an ancestor of audit repo HEAD")
    require(not ancestry.stderr, "ancestry check emitted stderr")

    inventory_blob = audit_git("rev-parse", f"{target_sha}:{INVENTORY_PATH}").stdout.decode().strip()
    dispatcher_blob = audit_git("rev-parse", f"{target_sha}:{DISPATCHER_PATH}").stdout.decode().strip()
    require(inventory_blob == EXPECTED_INVENTORY_BLOB, "reviewed inventory Git blob mismatch")
    require(dispatcher_blob == EXPECTED_DISPATCHER_BLOB, "reviewed dispatcher Git blob mismatch")
    require(index_snapshot() == before, "audit repo index changed during source validation")
    return before, head


def read_exact_blob(blob_oid: str) -> bytes:
    completed = audit_git("cat-file", "blob", blob_oid)
    require(completed.stdout, "reviewed Git blob is empty")
    return completed.stdout


def normalize_root_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    require(path.is_dir() and not path.is_symlink(), f"unsafe install directory: {path}")
    os.chown(path, 0, 0)
    os.chmod(path, 0o755)
    info = path.stat()
    require(info.st_uid == 0 and info.st_gid == 0, f"install directory owner mismatch: {path}")
    require(stat.S_IMODE(info.st_mode) == 0o755, f"install directory mode mismatch: {path}")


def atomic_root_write(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def install_or_verify_inventory(target_sha: str, payload: bytes) -> tuple[Path, str]:
    normalize_root_dir(AUDITS_ROOT)
    normalize_root_dir(INSTALL_ROOT)
    target = INSTALL_ROOT / target_sha
    if target.exists():
        require(target.is_dir() and not target.is_symlink(), "existing target install path unsafe")
        info = target.stat()
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755, "existing target directory metadata mismatch")
    else:
        target.mkdir(mode=0o755)
        os.chown(target, 0, 0)
        os.chmod(target, 0o755)

    inventory = target / "aldi_gate_d3_recovery_inventory.py"
    expected_sha = sha_bytes(payload)
    if inventory.exists():
        require(inventory.is_file() and not inventory.is_symlink(), "existing inventory path unsafe")
        info = inventory.stat()
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o444, "existing inventory metadata mismatch")
        require(sha_file(inventory) == expected_sha, "existing inventory content mismatch")
    else:
        atomic_root_write(inventory, payload, 0o444)

    unexpected = [entry.name for entry in target.iterdir() if entry.name != inventory.name]
    require(not unexpected, "unexpected member in exact target install directory")
    return inventory, expected_sha


def validate_inventory_as_audit_user(inventory: Path) -> None:
    completed = subprocess.run(
        [
            "/usr/sbin/runuser", "-u", AUDIT_USER, "--",
            "/usr/bin/env", "-i",
            f"HOME={AUDIT_HOME}", f"USER={AUDIT_USER}", f"LOGNAME={AUDIT_USER}",
            "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8",
            "/usr/bin/python3", str(inventory), "--help",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    require(completed.returncode == 0, "installed inventory CLI preflight failed for audit user")
    require(not completed.stderr, "installed inventory CLI preflight emitted stderr")


def validate_runner() -> None:
    active = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", RUNNER_SERVICE], check=False)
    require(active.returncode == 0, "audit runner inactive")
    groups = {entry.gr_name for entry in grp.getgrall() if RUNNER_USER in entry.gr_mem}
    groups.add(grp.getgrgid(pwd.getpwnam(RUNNER_USER).pw_gid).gr_name)
    require("docker" not in groups, "github-runner is in docker group")


def install_sudoers() -> None:
    SUDOERS_DST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=SUDOERS_DST.parent) as handle:
        handle.write(f"{RUNNER_USER} ALL=(root) NOPASSWD: {DISPATCH_DST} *\n")
        temp = Path(handle.name)
    try:
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o440)
        check = subprocess.run(
            ["/usr/sbin/visudo", "-cf", str(temp)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
        require(check.returncode == 0, "sudoers validation failed")
        os.replace(temp, SUDOERS_DST)
        os.chown(SUDOERS_DST, 0, 0)
        os.chmod(SUDOERS_DST, 0o440)
    finally:
        if temp.exists():
            temp.unlink()


def register_runtime(target_sha: str, inventory: Path, inventory_sha: str, dispatcher: bytes) -> str:
    dispatcher_sha = sha_bytes(dispatcher)
    atomic_root_write(DISPATCH_DST, dispatcher, 0o755)
    install_sudoers()
    config = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": target_sha,
        "inventory_file": str(inventory),
        "inventory_sha256": inventory_sha,
        "dispatcher_sha256": dispatcher_sha,
        "raw_evidence_export_authorized": False,
        "raw_exception_export_authorized": False,
        "archive_extraction_authorized": False,
        "review_pack_execution_authorized": False,
        "production_apply_authorized": False,
    }
    atomic_root_write(CONFIG_DST, (json.dumps(config, indent=2, sort_keys=True) + "\n").encode(), 0o600)
    return dispatcher_sha


def main() -> int:
    if os.geteuid() != 0:
        print("REGISTRATION_RESULT=BLOCKED reason=requires_root", file=sys.stderr)
        return 1
    if len(sys.argv) != 2 or sys.argv[1] != EXPECTED_TARGET_SHA:
        print("REGISTRATION_RESULT=BLOCKED reason=unexpected_target_sha", file=sys.stderr)
        return 2

    target_sha = sys.argv[1]
    try:
        before, head = validate_source_repo(target_sha)
        validate_runner()
        inventory_bytes = read_exact_blob(EXPECTED_INVENTORY_BLOB)
        dispatcher_bytes = read_exact_blob(EXPECTED_DISPATCHER_BLOB)
        require(index_snapshot() == before, "audit repo index changed while reading reviewed blobs")

        inventory, inventory_sha = install_or_verify_inventory(target_sha, inventory_bytes)
        validate_inventory_as_audit_user(inventory)
        dispatcher_sha = register_runtime(target_sha, inventory, inventory_sha, dispatcher_bytes)
        require(index_snapshot() == before, "audit repo index changed during non-rewind registration")
        require(audit_git("rev-parse", "HEAD").stdout.decode().strip() == head, "audit repo HEAD changed during registration")
        require(audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo became dirty")

        print("REGISTRATION_RESULT=PASS")
        print(f"AUDIT={AUDIT}")
        print(f"REGISTERED_COMMIT={target_sha}")
        print(f"AUDIT_REPO_HEAD_UNCHANGED={head}")
        print(f"INVENTORY_GIT_BLOB={EXPECTED_INVENTORY_BLOB}")
        print(f"DISPATCHER_GIT_BLOB={EXPECTED_DISPATCHER_BLOB}")
        print(f"INVENTORY_SHA256={inventory_sha}")
        print(f"DISPATCHER_SHA256={dispatcher_sha}")
        print("NON_REWIND_REGISTRATION=true")
        print("AUDIT_REPO_INDEX_PRESERVED=true")
        print("RUNNER_HAS_DOCKER_GROUP=false")
        print("RAW_EVIDENCE_EXPORT_AUTHORIZED=false")
        print("RAW_EXCEPTION_EXPORT_AUTHORIZED=false")
        print("ARCHIVE_EXTRACTION_AUTHORIZED=false")
        print("PRODUCTION_APPLY_AUTHORIZED=false")
        print("REVIEW_PACK_EXECUTION_AUTHORIZED=false")
        return 0
    except Exception as exc:
        print(f"REGISTRATION_RESULT=BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
