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
AUDITS_ROOT = Path("/usr/local/libexec/hermes-deals-audits")
INSTALL_ROOT = AUDITS_ROOT / "aldi-gate-d3-recovery-inventory"
INVENTORY_SOURCE = REPO / "tools/aldi_gate_d3_recovery_inventory.py"
DISPATCH_SOURCE = REPO / "tools/runner/aldi_gate_d3_recovery_inventory_dispatch.py"
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-aldi-gate-d3-recovery-inventory")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d3-recovery-inventory.json")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-aldi-gate-d3-recovery-inventory")
RUNNER_SERVICE = "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"


class InstallError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InstallError(message)


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


def audit_git(*args: str) -> bytes:
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
    require(completed.returncode == 0, f"audit git failed: {args[0]}")
    require(not completed.stderr, f"audit git emitted stderr: {args[0]}")
    return completed.stdout


def validate_repo(commit_sha: str) -> tuple[str, int, int, str]:
    before = index_snapshot()
    require(audit_git("branch", "--show-current").decode().strip() == "main", "audit repo branch mismatch")
    require(audit_git("rev-parse", "HEAD").decode().strip() == commit_sha, "audit repo SHA mismatch")
    require(audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all") == b"", "audit repo dirty")
    require(index_snapshot() == before, "audit repo index changed during verification")
    return before


def normalize_root_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o755)
    require(path.is_dir() and not path.is_symlink(), f"unsafe install directory: {path.name}")
    os.chown(path, 0, 0)
    os.chmod(path, 0o755)
    info = path.stat()
    require(info.st_uid == 0 and info.st_gid == 0, f"install directory owner mismatch: {path.name}")
    require(stat.S_IMODE(info.st_mode) == 0o755, f"install directory mode mismatch: {path.name}")


def install_files(commit_sha: str) -> tuple[Path, str]:
    normalize_root_dir(AUDITS_ROOT)
    normalize_root_dir(INSTALL_ROOT)
    target = INSTALL_ROOT / commit_sha
    require(not target.exists(), "inventory target already exists")
    target.mkdir(mode=0o755)
    os.chown(target, 0, 0)
    os.chmod(target, 0o755)
    try:
        inventory = target / "aldi_gate_d3_recovery_inventory.py"
        shutil.copyfile(INVENTORY_SOURCE, inventory, follow_symlinks=False)
        os.chown(inventory, 0, 0)
        os.chmod(inventory, 0o444)
        return inventory, sha_file(inventory)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def validate_inventory_as_audit_user(inventory: Path) -> None:
    readable = subprocess.run(
        ["/usr/sbin/runuser", "-u", AUDIT_USER, "--", "/usr/bin/test", "-r", str(inventory)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    require(readable.returncode == 0, "installed inventory is not readable by audit user")
    cli = subprocess.run(
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
    require(cli.returncode == 0, "installed inventory CLI preflight failed for audit user")
    require(not cli.stderr, "installed inventory CLI preflight emitted stderr")


def validate_runner() -> None:
    active = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", RUNNER_SERVICE], check=False)
    require(active.returncode == 0, "audit runner inactive")
    groups = {entry.gr_name for entry in grp.getgrall() if RUNNER_USER in entry.gr_mem}
    groups.add(grp.getgrgid(pwd.getpwnam(RUNNER_USER).pw_gid).gr_name)
    require("docker" not in groups, "github-runner is in docker group")


def install_dispatcher(commit_sha: str, inventory: Path, inventory_sha: str) -> None:
    DISPATCH_DST.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_DST.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DISPATCH_SOURCE, DISPATCH_DST, follow_symlinks=False)
    os.chown(DISPATCH_DST, 0, 0)
    os.chmod(DISPATCH_DST, 0o755)
    config = {
        "schema_version": 1,
        "audit": AUDIT,
        "commit_sha": commit_sha,
        "inventory_file": str(inventory),
        "inventory_sha256": inventory_sha,
        "dispatcher_sha256": sha_file(DISPATCH_DST),
        "raw_evidence_export_authorized": False,
        "raw_exception_export_authorized": False,
        "archive_extraction_authorized": False,
        "review_pack_execution_authorized": False,
        "production_apply_authorized": False,
    }
    CONFIG_DST.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chown(CONFIG_DST, 0, 0)
    os.chmod(CONFIG_DST, 0o600)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir="/etc/sudoers.d") as handle:
        handle.write(f"{RUNNER_USER} ALL=(root) NOPASSWD: {DISPATCH_DST} *\n")
        temp = Path(handle.name)
    try:
        os.chmod(temp, 0o440)
        check = subprocess.run(["/usr/sbin/visudo", "-cf", str(temp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        require(check.returncode == 0, "sudoers validation failed")
        os.replace(temp, SUDOERS_DST)
        os.chown(SUDOERS_DST, 0, 0)
        os.chmod(SUDOERS_DST, 0o440)
    finally:
        if temp.exists():
            temp.unlink()


def main() -> int:
    if os.geteuid() != 0:
        print("run as root", file=sys.stderr)
        return 1
    if len(sys.argv) != 2 or len(sys.argv[1]) != 40 or any(ch not in "0123456789abcdef" for ch in sys.argv[1]):
        print("usage: gate-d3-installer <merged-sha>", file=sys.stderr)
        return 2
    commit_sha = sys.argv[1]
    try:
        before = validate_repo(commit_sha)
        validate_runner()
        inventory, inventory_sha = install_files(commit_sha)
        validate_inventory_as_audit_user(inventory)
        install_dispatcher(commit_sha, inventory, inventory_sha)
        require(index_snapshot() == before, "audit repo index changed during installation")
        print("INSTALL_RESULT=PASS")
        print(f"AUDIT={AUDIT}")
        print(f"REGISTERED_COMMIT={commit_sha}")
        print(f"INVENTORY_SHA256={inventory_sha}")
        print("INSTALL_ROOT_TRAVERSABLE_BY_AUDIT_USER=true")
        print("INVENTORY_CLI_PREFLIGHT_PASS=true")
        print("INSTALLER_INDEX_OWNERSHIP_PRESERVED=true")
        print("RUNNER_HAS_DOCKER_GROUP=false")
        print("RAW_EVIDENCE_EXPORT_AUTHORIZED=false")
        print("RAW_EXCEPTION_EXPORT_AUTHORIZED=false")
        print("ARCHIVE_EXTRACTION_AUTHORIZED=false")
        print("PRODUCTION_APPLY_AUTHORIZED=false")
        print("REVIEW_PACK_EXECUTION_AUTHORIZED=false")
        return 0
    except Exception as exc:
        print(f"INSTALL_RESULT=BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
