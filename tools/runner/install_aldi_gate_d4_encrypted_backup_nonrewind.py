#!/usr/bin/env python3
from __future__ import annotations

import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any, Mapping

REPO = Path("/home/andris/hermes-deals-audit-source")
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
EXPECTED_TARGET_SHA = "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
EXPECTED_D4_BLOB = "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
EXPECTED_D3_BLOB = "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
EXPECTED_CONTRACT_BLOB = "3d29c0860d35d0f7e8d4c1b284036c131c23850e"
EXPECTED_DISPATCHER_BLOB = "1d0445530949e94c09bd89e678dc6996e2ea5549"
D4_PATH = "tools/aldi_gate_d4_backup_discovery.py"
D3_PATH = "tools/aldi_gate_d3_recovery_inventory.py"
CONTRACT_PATH = "tools/runner/aldi_gate_d4_encrypted_contract.py"
DISPATCHER_PATH = "tools/runner/aldi_gate_d4_encrypted_backup_dispatch.py"
INSTALLER_PATH = "tools/runner/install_aldi_gate_d4_encrypted_backup_nonrewind.py"
OWNER_REQUEST = Path("/home/andris/aldi-gate-d4-encrypted-request.json")
AGE_KEY = Path("/etc/rpi5-backup/age.key")
AGE_BINARIES = (Path("/usr/bin/age"), Path("/usr/local/bin/age"))
BACKUP_ROOT = Path("/opt/backups")
RUNTIME_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery")
BRIDGE_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-encrypted-backup-discovery")
DISPATCH_DST = Path("/usr/local/sbin/hermes-deals-aldi-gate-d4-encrypted-backup-discovery")
CONFIG_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery.json")
REQUEST_DST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery-request.json")
SUDOERS_DST = Path("/etc/sudoers.d/hermes-deals-aldi-gate-d4-encrypted-backup-discovery")
RUNNER_SERVICE = "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"
_VALIDATED_CONTRACT_BYTES: bytes | None = None


class RegistrationError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise RegistrationError(message)


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str, check: bool = True):
    completed = subprocess.run(
        [
            "/usr/sbin/runuser", "-u", AUDIT_USER, "--", "/usr/bin/env", "-i",
            "HOME=/home/andris", "USER=andris", "LOGNAME=andris", "PATH=/usr/local/bin:/usr/bin:/bin",
            "LANG=C.UTF-8", "GIT_OPTIONAL_LOCKS=0", "/usr/bin/git", "-C", str(REPO), *args,
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, check=False, timeout=30,
    )
    if check:
        require(completed.returncode == 0 and not completed.stderr, f"git failed: {args[0]}")
    return completed


def text(*args: str) -> str:
    return git(*args).stdout.decode().strip()


def index_snapshot():
    path = REPO / ".git/index"
    require(path.is_file() and not path.is_symlink() and not (REPO / ".git/index.lock").exists(), "audit index unsafe")
    info = path.stat()
    return info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_size, sha_file(path)


def blob(oid: str) -> bytes:
    payload = git("cat-file", "blob", oid).stdout
    require(payload, "reviewed Git blob is empty")
    return payload


def validate_source(target: str):
    global _VALIDATED_CONTRACT_BYTES
    before = index_snapshot()
    require(text("branch", "--show-current") == "main", "audit repo branch mismatch")
    require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo not clean")
    head = text("rev-parse", "HEAD")
    require(target == EXPECTED_TARGET_SHA and text("rev-parse", "--verify", f"{target}^{{commit}}") == target, "target unavailable")
    ancestry = git("merge-base", "--is-ancestor", target, head, check=False)
    require(ancestry.returncode == 0 and not ancestry.stderr, "target not ancestor")
    for path, expected in ((D4_PATH, EXPECTED_D4_BLOB), (D3_PATH, EXPECTED_D3_BLOB)):
        require(text("rev-parse", f"{target}:{path}") == expected, f"reviewed blob drift: {path}")
    for path, expected in ((CONTRACT_PATH, EXPECTED_CONTRACT_BLOB), (DISPATCHER_PATH, EXPECTED_DISPATCHER_BLOB)):
        require(text("rev-parse", f"HEAD:{path}") == expected, f"current blob drift: {path}")
    installer_blob = text("rev-parse", f"HEAD:{INSTALLER_PATH}")
    require(installer_blob, "installer blob unavailable")
    require(blob(installer_blob) == Path(__file__).read_bytes(), "installer working-tree identity drift")
    contract_bytes = blob(EXPECTED_CONTRACT_BLOB)
    require((REPO / CONTRACT_PATH).read_bytes() == contract_bytes, "contract working-tree identity drift")
    _VALIDATED_CONTRACT_BYTES = contract_bytes
    require(index_snapshot() == before, "index changed")
    return before, head


def regular_root_file(path: Path, mode: int) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode


def audit_file(path: Path, mode: int) -> bool:
    try:
        info = path.lstat()
        user = pwd.getpwnam(AUDIT_USER)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == user.pw_uid and info.st_gid == user.pw_gid and stat.S_IMODE(info.st_mode) == mode


def load_contract() -> ModuleType:
    source = _VALIDATED_CONTRACT_BYTES
    if source is None:
        path = REPO / CONTRACT_PATH
        if not path.exists():
            path = Path(__file__).with_name("aldi_gate_d4_encrypted_contract.py")
        require(path.is_file() and not path.is_symlink(), "contract source unavailable")
        source = path.read_bytes()
    module = ModuleType("d4e_contract_registration")
    try:
        code = compile(source.decode("utf-8"), f"<git-blob:{EXPECTED_CONTRACT_BLOB}>", "exec")
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise RegistrationError("contract compile failed") from exc
    exec(code, module.__dict__)
    return module


def validate_request_payload(payload: Mapping[str, Any]):
    module = load_contract()
    try:
        return module.validate_request_payload(payload, backup_root=BACKUP_ROOT, file_check=regular_root_file, hasher=sha_file)
    except Exception as exc:
        raise RegistrationError(str(exc)) from exc


def load_request():
    require(audit_file(OWNER_REQUEST, 0o600), "owner request missing or unsafe")
    raw = OWNER_REQUEST.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("owner request invalid") from exc
    require(isinstance(payload, Mapping), "owner request root invalid")
    validate_request_payload(payload)
    return raw, hashlib.sha256(raw).hexdigest()


def validate_age() -> tuple[Path, str]:
    require(regular_root_file(AGE_KEY, 0o600), "age identity missing or unsafe")
    for path in AGE_BINARIES:
        try:
            info = path.lstat()
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == 0 and not (stat.S_IMODE(info.st_mode) & 0o022):
            return path, sha_file(path)
    raise RegistrationError("reviewed age executable unavailable")


def validate_runner() -> None:
    require(subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", RUNNER_SERVICE], check=False).returncode == 0, "audit runner inactive")
    user = pwd.getpwnam(RUNNER_USER)
    groups = {group.gr_name for group in grp.getgrall() if RUNNER_USER in group.gr_mem} | {grp.getgrgid(user.pw_gid).gr_name}
    require("docker" not in groups, "runner docker group forbidden")


def mkdir_root(path: Path, mode: int = 0o755) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    require(path.is_dir() and not path.is_symlink(), "install dir unsafe")
    os.chown(path, 0, 0)
    os.chmod(path, mode)


def atomic(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def runtime(target: str, d4_bytes: bytes, d3_bytes: bytes) -> Path:
    mkdir_root(RUNTIME_ROOT)
    root = RUNTIME_ROOT / target
    if root.exists():
        require(root.is_dir() and not root.is_symlink(), "existing runtime target unsafe")
        info = root.stat()
        require(info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o755, "existing runtime metadata drift")
    else:
        mkdir_root(root)
    for name, payload in (("aldi_gate_d4_backup_discovery.py", d4_bytes), ("aldi_gate_d3_recovery_inventory.py", d3_bytes)):
        path = root / name
        digest = sha_bytes(payload)
        if path.exists():
            require(regular_root_file(path, 0o444) and sha_file(path) == digest, f"runtime drift: {name}")
        else:
            atomic(path, payload, 0o444)
    require(sha_file(root / "aldi_gate_d3_recovery_inventory.py") == "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8", "D3 SHA drift")
    return root


def sudoers() -> None:
    line = f"{RUNNER_USER} ALL=(root) NOPASSWD: {DISPATCH_DST} {EXPECTED_TARGET_SHA} /home/github-runner/_work/_temp/hermes-deals-aldi-gate-d4-encrypted-backup-*\n"
    SUDOERS_DST.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=SUDOERS_DST.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(line.encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temp, 0, 0)
        os.chmod(temp, 0o440)
        check = subprocess.run(["/usr/sbin/visudo", "-cf", str(temp)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
        require(check.returncode == 0, "sudoers invalid")
        os.replace(temp, SUDOERS_DST)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 2 or sys.argv[1] != EXPECTED_TARGET_SHA:
        return 2
    try:
        before, head = validate_source(sys.argv[1])
        validate_runner()
        age_file, age_sha = validate_age()
        request, request_sha = load_request()
        d4_bytes = blob(EXPECTED_D4_BLOB)
        d3_bytes = blob(EXPECTED_D3_BLOB)
        contract = blob(EXPECTED_CONTRACT_BLOB)
        dispatcher = blob(EXPECTED_DISPATCHER_BLOB)
        require(index_snapshot() == before, "index changed reading blobs")
        root = runtime(sys.argv[1], d4_bytes, d3_bytes)
        mkdir_root(BRIDGE_ROOT)
        atomic(BRIDGE_ROOT / "contract.py", contract, 0o444)
        atomic(DISPATCH_DST, dispatcher, 0o755)
        atomic(REQUEST_DST, request, 0o600)
        sudoers()
        authority_flags = load_contract().AUTHORITY_FLAGS
        config = {
            "schema_version": 2,
            "audit": "aldi-gate-d4-encrypted-backup-discovery",
            "commit_sha": sys.argv[1],
            "d4_file": str(root / "aldi_gate_d4_backup_discovery.py"),
            "d4_sha256": sha_bytes(d4_bytes),
            "d3_file": str(root / "aldi_gate_d3_recovery_inventory.py"),
            "d3_sha256": sha_bytes(d3_bytes),
            "contract_sha256": sha_bytes(contract),
            "request_file": str(REQUEST_DST),
            "request_sha256": request_sha,
            "dispatcher_sha256": sha_bytes(dispatcher),
            "age_file": str(age_file),
            "age_sha256": age_sha,
            **{key: False for key in authority_flags},
        }
        atomic(CONFIG_DST, (json.dumps(config, sort_keys=True, indent=2) + "\n").encode(), 0o600)
        require(index_snapshot() == before and text("rev-parse", "HEAD") == head, "audit repo identity changed")
        require(git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo became dirty")
        print("REGISTRATION_RESULT=PASS")
        print(f"REGISTERED_COMMIT={sys.argv[1]}")
        print(f"AUDIT_REPO_HEAD_UNCHANGED={head}")
        print(f"D4_GIT_BLOB={EXPECTED_D4_BLOB}")
        print(f"D3_GIT_BLOB={EXPECTED_D3_BLOB}")
        print(f"CONTRACT_GIT_BLOB={EXPECTED_CONTRACT_BLOB}")
        print(f"DISPATCHER_GIT_BLOB={EXPECTED_DISPATCHER_BLOB}")
        print(f"REQUEST_SHA256={request_sha}")
        print(f"AGE_SHA256={age_sha}")
        print("AGE_IDENTITY_CONTENT_EXPORTED=false")
        print("DECRYPTION_EXECUTED=false")
        print("NON_REWIND_REGISTRATION=true")
        print("AUDIT_REPO_INDEX_PRESERVED=true")
        print("RUNNER_HAS_DOCKER_GROUP=false")
        for flag in authority_flags:
            print(f"{flag.upper()}=false")
        return 0
    except Exception as exc:
        print(f"REGISTRATION_RESULT=BLOCKED error_type={type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
