#!/usr/bin/env python3
from __future__ import annotations

import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from types import ModuleType
from typing import Any, Mapping

AUDIT = "aldi-gate-d4-encrypted-backup-discovery"
EXPECTED_TARGET_SHA = "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
EXPECTED_D3_SHA256 = "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
AUTHORITY_FLAGS = (
    "raw_evidence_export_authorized", "raw_exception_export_authorized", "network_acquisition_authorized",
    "archive_extraction_authorized", "source_or_corpus_mutation_authorized", "manifest_regeneration_authorized",
    "parser_execution_authorized", "candidate_creation_authorized", "review_or_publication_write_authorized",
    "production_database_write_authorized", "production_deployment_authorized", "scheduler_systemd_canary_authorized",
    "destructive_cleanup_authorized", "newer_41_plus_41_substitution_authorized", "historical_recovery_binding_authorized",
    "irrecoverable_decision_recording_authorized",
)
HEX_RE = re.compile(r"[0-9a-f]{64}")
CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery.json")
REQUEST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-encrypted-backup-discovery-request.json")
CONTRACT_PATH = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-encrypted-backup-discovery/contract.py")
INSTALLED_DISPATCHER = Path("/usr/local/sbin/hermes-deals-aldi-gate-d4-encrypted-backup-discovery")
RUNTIME_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery")
EXPORT_ROOT = Path("/home/github-runner/_work/_temp")
EXPORT_PREFIX = "hermes-deals-aldi-gate-d4-encrypted-backup-"
BACKUP_ROOT = Path("/opt/backups")
AGE_KEY = Path("/etc/rpi5-backup/age.key")
TMPFS_PARENT = Path("/dev/shm")
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
AGE_BINARIES = {Path("/usr/bin/age"), Path("/usr/local/bin/age")}
_CONTRACT: ModuleType | None = None


class EncryptedDispatchError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise EncryptedDispatchError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_root_file(path: Path, mode: int | None = None) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == 0
        and info.st_gid == 0
        and (mode is None or stat.S_IMODE(info.st_mode) == mode)
    )


def _import_contract(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("d4e_contract", path)
    require(spec is not None and spec.loader is not None, "contract import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract() -> ModuleType:
    global _CONTRACT
    if _CONTRACT is not None:
        return _CONTRACT
    require(Path(__file__).resolve() != INSTALLED_DISPATCHER, "installed dispatcher contract was not verified")
    source_contract = Path(__file__).with_name("aldi_gate_d4_encrypted_contract.py")
    require(source_contract.is_file() and not source_contract.is_symlink(), "source contract unavailable")
    _CONTRACT = _import_contract(source_contract)
    return _CONTRACT


def validate_result(payload: Mapping[str, Any], expected_count: int) -> None:
    contract = _contract()
    try:
        contract.validate_result(payload, expected_count)
    except contract.ContractError as exc:
        raise EncryptedDispatchError(str(exc)) from exc


def _preload_config(commit: str) -> dict[str, Any]:
    require(regular_root_file(CONFIG, 0o600), "config missing or unsafe")
    try:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EncryptedDispatchError("config invalid") from exc
    fields = {
        "schema_version", "audit", "commit_sha", "d4_file", "d4_sha256", "d3_file", "d3_sha256",
        "contract_sha256", "request_file", "request_sha256", "dispatcher_sha256", "age_file", "age_sha256",
        *AUTHORITY_FLAGS,
    }
    require(isinstance(payload, dict) and set(payload) == fields, "config schema mismatch")
    require(payload.get("schema_version") == 2 and payload.get("audit") == AUDIT, "config identity mismatch")
    require(payload.get("commit_sha") == commit == EXPECTED_TARGET_SHA, "config commit mismatch")
    require(payload.get("d3_sha256") == EXPECTED_D3_SHA256, "D3 SHA mismatch")
    for field in ("d4_sha256", "contract_sha256", "request_sha256", "dispatcher_sha256", "age_sha256"):
        require(isinstance(payload.get(field), str) and HEX_RE.fullmatch(payload[field]) is not None, f"{field} invalid")
    require(payload.get("request_file") == str(REQUEST), "request path mismatch")
    age = Path(str(payload.get("age_file") or ""))
    require(age in AGE_BINARIES, "age executable path mismatch")
    require(all(payload.get(flag) is False for flag in AUTHORITY_FLAGS), "config authority drift")
    return payload


def _verify_and_load_installed_contract(config: Mapping[str, Any]) -> ModuleType:
    global _CONTRACT
    require(regular_root_file(CONTRACT_PATH, 0o444), "contract missing or unsafe")
    require(sha_file(CONTRACT_PATH) == config["contract_sha256"], "contract SHA drift")
    require(regular_root_file(INSTALLED_DISPATCHER, 0o755), "dispatcher missing or unsafe")
    require(sha_file(INSTALLED_DISPATCHER) == config["dispatcher_sha256"], "dispatcher SHA drift")
    module = _import_contract(CONTRACT_PATH)
    require(module.AUDIT == AUDIT and module.TARGET == EXPECTED_TARGET_SHA, "contract identity drift")
    require(module.D3_SHA == EXPECTED_D3_SHA256, "contract D3 pin drift")
    require(tuple(module.AUTHORITY_FLAGS) == AUTHORITY_FLAGS, "contract authority schema drift")
    _CONTRACT = module
    return module


def runner_in_docker_group(name: str) -> bool:
    user = pwd.getpwnam(name)
    return any(group.gr_name == "docker" and (name in group.gr_mem or group.gr_gid == user.pw_gid) for group in grp.getgrall())


def validate_export_dir(path: Path, user: pwd.struct_passwd) -> Path:
    require(path.is_absolute() and ".." not in path.parts, "export path invalid")
    require(path.parent.resolve(strict=True) == EXPORT_ROOT.resolve(strict=True), "export parent mismatch")
    require(path.name.startswith(EXPORT_PREFIX), "export prefix mismatch")
    require(path.is_dir() and not path.is_symlink(), "export directory missing")
    info = path.lstat()
    require(info.st_uid == user.pw_uid and info.st_gid == user.pw_gid, "export owner mismatch")
    require(stat.S_IMODE(info.st_mode) == 0o700 and not any(path.iterdir()), "export directory unsafe")
    return path


def load_config(commit: str) -> dict[str, Any]:
    config = _preload_config(commit)
    _verify_and_load_installed_contract(config)
    return config


def load_request(config: Mapping[str, Any]):
    contract = _contract()
    require(regular_root_file(REQUEST, 0o600), "request missing or unsafe")
    require(sha_file(REQUEST) == config["request_sha256"], "request SHA drift")
    try:
        payload = json.loads(REQUEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EncryptedDispatchError("request invalid") from exc
    require(isinstance(payload, dict), "request root invalid")
    try:
        rows = contract.validate_request_payload(
            payload,
            backup_root=BACKUP_ROOT,
            file_check=regular_root_file,
            hasher=sha_file,
        )
    except contract.ContractError as exc:
        raise EncryptedDispatchError(str(exc)) from exc
    return payload, rows


def validate_runtime(config: Mapping[str, Any], commit: str) -> Path:
    contract = _contract()
    runtime = RUNTIME_ROOT / commit
    d4 = runtime / "aldi_gate_d4_backup_discovery.py"
    d3 = runtime / "aldi_gate_d3_recovery_inventory.py"
    require(contract.root_runtime_dir(runtime), "runtime directory missing or unsafe")
    require(contract.root_runtime_file(d4) and contract.root_runtime_file(d3), "runtime missing or unsafe")
    require(config["d4_file"] == str(d4) and config["d3_file"] == str(d3), "runtime path drift")
    require(sha_file(d4) == config["d4_sha256"] and sha_file(d3) == EXPECTED_D3_SHA256, "runtime identity drift")
    require(sha_file(CONTRACT_PATH) == config["contract_sha256"], "contract SHA drift")
    require(sha_file(INSTALLED_DISPATCHER) == config["dispatcher_sha256"], "dispatcher SHA drift")
    return d4


def validate_age_key() -> None:
    require(regular_root_file(AGE_KEY, 0o600), "age identity missing or unsafe")


def select_age_binary(config: Mapping[str, Any]) -> Path:
    path = Path(str(config["age_file"]))
    require(path in AGE_BINARIES, "age executable path mismatch")
    try:
        info = path.lstat()
    except OSError as exc:
        raise EncryptedDispatchError("reviewed age executable unavailable") from exc
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), "age executable unsafe")
    require(info.st_uid == 0 and not (stat.S_IMODE(info.st_mode) & 0o022), "age executable ownership/mode unsafe")
    require(sha_file(path) == config["age_sha256"], "age executable SHA drift")
    return path


def mount_fstype(path: Path) -> str | None:
    target = str(path.resolve(strict=True))
    best = None
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        separator = parts.index("-") if "-" in parts else -1
        if separator > 0 and target == parts[4]:
            best = parts[separator + 1]
    return best


def prepare_tmpfs(user: pwd.struct_passwd, total: int) -> Path:
    require(mount_fstype(TMPFS_PARENT) == "tmpfs", "plaintext parent is not tmpfs")
    free = shutil.disk_usage(TMPFS_PARENT).free
    require(free >= max(total * 2, 64 * 1024 * 1024), "insufficient tmpfs capacity")
    path = Path(tempfile.mkdtemp(prefix="hermes-d4e-", dir=TMPFS_PARENT))
    os.chown(path, user.pw_uid, user.pw_gid)
    os.chmod(path, 0o700)
    require(mount_fstype(TMPFS_PARENT) == "tmpfs", "plaintext parent changed filesystem")
    return path


def _sha_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    for chunk in iter(lambda: os.read(fd, 1024 * 1024), b""):
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def decrypt_one(age: Path, user: pwd.struct_passwd, input_id: str, source: Path, expected: str, run_dir: Path) -> Path:
    before = source.lstat()
    require(stat.S_ISREG(before.st_mode) and not source.is_symlink(), "ciphertext changed type")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(source, flags)
    destination = run_dir / f"{input_id}.tar.gz"
    out_fd = -1
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), "ciphertext changed during open")
        require(_sha_fd(fd) == expected, "ciphertext SHA mismatch")
        out_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(out_fd, "wb", closefd=False) as output:
            completed = subprocess.run(
                [str(age), "-d", "-i", str(AGE_KEY), f"/proc/self/fd/{fd}"],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.PIPE,
                pass_fds=(fd,),
                check=False,
                timeout=180,
            )
            output.flush()
            os.fsync(output.fileno())
        require(completed.returncode == 0, "age decrypt failed")
        after = os.fstat(fd)
        require(
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns),
            "ciphertext changed during decrypt",
        )
        require(destination.stat().st_size > 2, "decrypted payload empty")
        with destination.open("rb") as handle:
            require(handle.read(2) == b"\x1f\x8b", "decrypted payload is not gzip")
        try:
            with tarfile.open(destination, "r:gz") as archive:
                for _member in archive:
                    pass
        except (tarfile.TarError, OSError) as exc:
            raise EncryptedDispatchError("decrypted payload is not a valid tar.gz") from exc
        os.chown(destination, user.pw_uid, user.pw_gid)
        os.chmod(destination, 0o600)
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if out_fd >= 0:
            os.close(out_fd)
        os.close(fd)


def audit_user_command(*args: str):
    return subprocess.run(
        [
            "/usr/sbin/runuser", "-u", AUDIT_USER, "--", "/usr/bin/env", "-i",
            "HOME=/home/andris", "USER=andris", "LOGNAME=andris", "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", *args,
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=180,
    )


def write_manifest(export: Path, *, commit_sha: str, request_sha: str, d4_sha: str, result: dict[str, Any], encrypted_rows: list[tuple[str, Path, str]]) -> None:
    contract = _contract()
    payload = contract.evidence_manifest(commit_sha=commit_sha, request_sha=request_sha, d4_sha=d4_sha, result=result, rows=encrypted_rows)
    (export / "dispatcher-evidence-manifest.json").write_bytes(canonical_bytes(payload) + b"\n")


def cleanup_tmpfs(path: Path | None) -> None:
    if path is None:
        return
    shutil.rmtree(path)
    require(not path.exists(), "tmpfs plaintext cleanup failed")


def main() -> int:
    stage = "argument_validation"
    reason = "dispatch_error"
    export = None
    run_dir = None
    try:
        require(os.geteuid() == 0 and len(sys.argv) == 3, "dispatcher invocation invalid")
        commit, raw = sys.argv[1], sys.argv[2]
        require(commit == EXPECTED_TARGET_SHA, "unexpected runtime SHA")
        stage = "runner_validation"
        runner = pwd.getpwnam(RUNNER_USER)
        user = pwd.getpwnam(AUDIT_USER)
        require(not runner_in_docker_group(RUNNER_USER), "runner docker group forbidden")
        stage = "export_validation"
        export = validate_export_dir(Path(raw), runner)
        stage = "config_validation"
        config = load_config(commit)
        stage = "request_validation"
        _request, rows = load_request(config)
        stage = "runtime_validation"
        d4 = validate_runtime(config, commit)
        stage = "age_environment_validation"
        validate_age_key()
        age = select_age_binary(config)
        stage = "tmpfs_preparation"
        run_dir = prepare_tmpfs(user, sum(path.stat().st_size for _id, path, _digest in rows))
        files = []
        for input_id, path, digest in rows:
            stage = "age_decryption"
            files.append({"id": input_id, "path": str(decrypt_one(age, user, input_id, path, digest, run_dir))})
        internal = run_dir / "request.json"
        internal.write_bytes(canonical_bytes({
            "schema_version": 2,
            "issue_number": _contract().PARENT_ISSUE,
            "authoritative_source_set_complete": False,
            "roots": [],
            "files": files,
        }) + b"\n")
        os.chown(internal, user.pw_uid, user.pw_gid)
        os.chmod(internal, 0o600)
        result_path = run_dir / "result.json"
        stage = "d4_cli_preflight"
        require(audit_user_command("/usr/bin/python3", str(d4), "--help").returncode == 0, "D4 CLI preflight failed")
        stage = "d4_execution"
        completed = audit_user_command("/usr/bin/python3", str(d4), "--request", str(internal), "--output", str(result_path))
        reason = f"d4_exit_{completed.returncode}"
        require(completed.returncode == 0, "D4 execution failed")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        stage = "result_validation"
        validate_result(result, len(rows))
        stage = "tmpfs_cleanup"
        cleanup_tmpfs(run_dir)
        run_dir = None
        stage = "result_export"
        (export / "diagnostic-result.json").write_bytes(canonical_bytes(result) + b"\n")
        (export / "diagnostic-exit-code.txt").write_text("0\n", encoding="utf-8")
        write_manifest(export, commit_sha=commit, request_sha=config["request_sha256"], d4_sha=config["d4_sha256"], result=result, encrypted_rows=rows)
        return 0
    except Exception as exc:
        if run_dir is not None:
            try:
                shutil.rmtree(run_dir)
            except Exception:
                reason = "tmpfs_cleanup_failed"
        if export is not None:
            failure = {
                "schema_version": 1,
                "audit": AUDIT,
                "error_type": type(exc).__name__,
                "failure_stage": stage,
                "reason_code": reason,
                "raw_exception_exported": False,
                "raw_stderr_exported": False,
                "raw_request_exported": False,
                "age_identity_exported": False,
                "plaintext_exported": False,
            }
            try:
                (export / "diagnostic-failure.json").write_bytes(canonical_bytes(failure) + b"\n")
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
