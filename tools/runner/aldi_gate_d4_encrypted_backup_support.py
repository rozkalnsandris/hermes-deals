from __future__ import annotations

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
import tarfile
import tempfile
from types import ModuleType
from typing import Any, Mapping

AUDIT = "aldi-gate-d4-backup-discovery"
ISSUE_NUMBER = 631
CONFIG = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-backup-discovery.json")
REQUEST = Path("/etc/hermes-deals-audits.d/aldi-gate-d4-backup-discovery-request.json")
RUNTIME_ROOT = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery")
EXPECTED_D3_SHA256 = "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
EXPECTED_BASE_DISPATCHER_BLOB = "f76ab8dfa938162dea038a2ef981c9002d5382e5"
EXPECTED_BASE_DISPATCHER_SHA256 = "894d8e60179552abf589577cd305ebc92427b1d0746955b15b1eb553e6961723"
BASE_DISPATCHER = Path(
    "/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery-dispatch-base/"
    f"{EXPECTED_BASE_DISPATCHER_BLOB}.py"
)
AGE = Path("/usr/bin/age")
AGE_IDENTITY = Path("/etc/rpi5-backup/age.key")
TMPFS_ROOT = Path("/run/hermes-deals-audits/aldi-gate-d4-backup-discovery")
AUDIT_USER = "andris"
RUNNER_USER = "github-runner"
REQUEST_SCHEMA_V1 = 1
REQUEST_SCHEMA_V2 = 2
REQUEST_SCHEMA_V3 = 3
MAX_INPUTS = 8
INPUT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
AUTHORITY_FLAGS = (
    "raw_evidence_export_authorized", "raw_exception_export_authorized",
    "network_acquisition_authorized", "archive_extraction_authorized",
    "source_or_corpus_mutation_authorized", "manifest_regeneration_authorized",
    "parser_execution_authorized", "candidate_creation_authorized",
    "review_or_publication_write_authorized", "production_database_write_authorized",
    "production_deployment_authorized", "scheduler_systemd_canary_authorized",
    "destructive_cleanup_authorized", "newer_41_plus_41_substitution_authorized",
    "historical_recovery_binding_authorized", "irrecoverable_decision_recording_authorized",
)
CONFIG_FIELDS = {
    "schema_version", "audit", "commit_sha", "d4_file", "d4_sha256", "d3_file", "d3_sha256",
    "request_file", "request_sha256", "dispatcher_sha256", "age_file", "age_sha256", *AUTHORITY_FLAGS,
}


class D4EncryptedDispatchError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D4EncryptedDispatchError(message)


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and HEX64_RE.fullmatch(value) is not None


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def root_regular_file(path: Path, modes: set[int]) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode) and not path.is_symlink()
        and info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) in modes
    )


def load_base() -> ModuleType:
    require(root_regular_file(BASE_DISPATCHER, {0o444}), "base dispatcher support missing or unsafe")
    require(sha_file(BASE_DISPATCHER) == EXPECTED_BASE_DISPATCHER_SHA256, "base dispatcher support SHA drift")
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_dispatch_base_v3", BASE_DISPATCHER)
    require(spec is not None and spec.loader is not None, "base dispatcher import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.AUDIT == AUDIT and module.ISSUE_NUMBER == ISSUE_NUMBER, "base dispatcher identity drift")
    require(module.EXPECTED_D3_SHA256 == EXPECTED_D3_SHA256, "base dispatcher D3 pin drift")
    return module


def load_config(base: Any, commit_sha: str) -> dict[str, Any]:
    require(base.regular_root_file(CONFIG), "config missing or unsafe")
    try:
        payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D4EncryptedDispatchError("config invalid") from exc
    require(isinstance(payload, dict) and set(payload) == CONFIG_FIELDS, "config schema mismatch")
    require(payload.get("schema_version") == 2 and payload.get("audit") == AUDIT, "config identity mismatch")
    require(payload.get("commit_sha") == commit_sha, "config commit mismatch")
    require(is_hex64(payload.get("d4_sha256")), "D4 SHA invalid")
    require(payload.get("d3_sha256") == EXPECTED_D3_SHA256, "D3 SHA mismatch")
    for field in ("request_sha256", "dispatcher_sha256", "age_sha256"):
        require(is_hex64(payload.get(field)), f"{field} invalid")
    require(payload.get("age_file") == str(AGE), "age path mismatch")
    for flag in AUTHORITY_FLAGS:
        require(payload.get(flag) is False, f"unsafe config flag: {flag}")
    runtime = RUNTIME_ROOT / commit_sha
    require(payload.get("d4_file") == str(runtime / "aldi_gate_d4_backup_discovery.py"), "D4 path mismatch")
    require(payload.get("d3_file") == str(runtime / "aldi_gate_d3_recovery_inventory.py"), "D3 path mismatch")
    require(payload.get("request_file") == str(REQUEST), "request path mismatch")
    return payload


def validate_runtime(base: Any, config: Mapping[str, Any], commit_sha: str, dispatcher: Path) -> Path:
    runtime = RUNTIME_ROOT / commit_sha
    require(base.root_runtime_dir(runtime), "runtime directory missing or unsafe")
    d4 = Path(str(config["d4_file"])); d3 = Path(str(config["d3_file"]))
    require(d4.parent == runtime and d3.parent == runtime, "runtime path escaped target directory")
    require(base.root_runtime_file(d4) and base.root_runtime_file(d3), "runtime missing or unsafe")
    require(base.sha_file(d4) == config["d4_sha256"], "D4 runtime SHA drift")
    require(base.sha_file(d3) == EXPECTED_D3_SHA256, "D3 runtime SHA drift")
    require(base.sha_file(dispatcher) == config["dispatcher_sha256"], "dispatcher SHA drift")
    require(root_regular_file(AGE, {0o755, 0o555}), "age executable missing or unsafe")
    require(sha_file(AGE) == config["age_sha256"], "age executable SHA drift")
    require(root_regular_file(AGE_IDENTITY, {0o600}), "age identity missing or unsafe")
    return d4


def _validate_id(raw: Any, seen: set[str]) -> str:
    require(isinstance(raw, str) and INPUT_ID_RE.fullmatch(raw) is not None, "invalid backup input id")
    require(raw not in seen, "duplicate backup input id")
    seen.add(raw)
    return raw


def _resolve_encrypted_file(raw: Any) -> Path:
    require(isinstance(raw, str) and raw.startswith("/"), "encrypted backup file must be absolute")
    path = Path(raw)
    require(".." not in path.parts and not path.is_symlink(), "encrypted backup file path unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise D4EncryptedDispatchError("encrypted backup file missing") from exc
    require(resolved == path and resolved.is_file() and not resolved.is_symlink(), "encrypted backup file unsafe")
    require(resolved.name.endswith(".tar.gz.age"), "encrypted backup file suffix invalid")
    return resolved


def validate_v3_request(base: Any, payload: Mapping[str, Any]):
    require(set(payload) == {"schema_version", "issue_number", "authoritative_source_set_complete", "roots", "files", "encrypted_files"}, "request fields mismatch")
    require(payload.get("schema_version") == 3 and payload.get("issue_number") == ISSUE_NUMBER, "request identity mismatch")
    complete = payload.get("authoritative_source_set_complete")
    roots_raw = payload.get("roots"); files_raw = payload.get("files"); encrypted_raw = payload.get("encrypted_files")
    require(isinstance(complete, bool), "request completeness flag invalid")
    require(isinstance(roots_raw, list) and isinstance(files_raw, list) and isinstance(encrypted_raw, list), "request input lists invalid")
    require(roots_raw or files_raw or encrypted_raw, "at least one explicit backup input is required")
    require(len(roots_raw) + len(files_raw) + len(encrypted_raw) <= MAX_INPUTS, "request input count invalid")
    ids: set[str] = set(); root_paths: set[Path] = set(); file_paths: set[Path] = set(); encrypted_paths: set[Path] = set()
    roots = []; files = []; encrypted = []
    for row in roots_raw:
        require(isinstance(row, Mapping) and set(row) == {"id", "path"}, "request root entry invalid")
        input_id = _validate_id(row.get("id"), ids); root = base._resolve_original_root(row.get("path"))
        require(root not in root_paths, "duplicate request root path")
        for existing in root_paths:
            require(root not in existing.parents and existing not in root.parents, "request roots must not overlap")
        root_paths.add(root); roots.append((input_id, root))
    for row in files_raw:
        require(isinstance(row, Mapping) and set(row) == {"id", "path"}, "request file entry invalid")
        input_id = _validate_id(row.get("id"), ids); path = base._resolve_original_file(row.get("path"))
        require(path not in file_paths, "duplicate request file path")
        require(all(root not in path.parents for root in root_paths), "backup file must not be inside a designated root")
        file_paths.add(path); files.append((input_id, path))
    for row in encrypted_raw:
        require(isinstance(row, Mapping) and set(row) == {"id", "path", "ciphertext_sha256"}, "request encrypted file entry invalid")
        input_id = _validate_id(row.get("id"), ids); path = _resolve_encrypted_file(row.get("path")); digest = row.get("ciphertext_sha256")
        require(is_hex64(digest), "encrypted backup ciphertext SHA invalid")
        require(path not in encrypted_paths and path not in file_paths, "duplicate backup input path")
        require(all(root not in path.parents for root in root_paths), "encrypted backup file must not be inside a designated root")
        encrypted_paths.add(path); encrypted.append((input_id, path, str(digest)))
    roots.sort(); files.sort(); encrypted.sort()
    return complete, roots, files, encrypted


def load_request() -> dict[str, Any]:
    try:
        payload = json.loads(REQUEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D4EncryptedDispatchError("request invalid") from exc
    require(isinstance(payload, dict), "request root invalid")
    return payload


def _decode_mount(value: str) -> str:
    for src, dst in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(src, dst)
    return value


def filesystem_type(path: Path) -> str:
    resolved = path.resolve(strict=True); best_parts = -1; best_type = ""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise D4EncryptedDispatchError("mountinfo unavailable") from exc
    for line in lines:
        fields = line.split()
        if "-" not in fields or len(fields) < 7: continue
        sep = fields.index("-"); mount = Path(_decode_mount(fields[4]))
        try: resolved.relative_to(mount)
        except ValueError: continue
        if len(mount.parts) > best_parts:
            best_parts = len(mount.parts); best_type = fields[sep + 1]
    require(best_type, "filesystem type unavailable")
    return best_type


def prepare_tmpfs_staging(base: Any):
    require(Path("/run").is_dir() and not Path("/run").is_symlink(), "/run unsafe")
    require(filesystem_type(Path("/run")) == "tmpfs", "/run is not tmpfs")
    parent = TMPFS_ROOT.parent
    parent.mkdir(mode=0o755, parents=False, exist_ok=True)
    require(parent.is_dir() and not parent.is_symlink(), "tmpfs parent unsafe")
    info = parent.lstat(); require(info.st_uid == 0 and info.st_gid == 0, "tmpfs parent owner mismatch"); os.chmod(parent, 0o755)
    TMPFS_ROOT.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = TMPFS_ROOT.lstat(); require(info.st_uid == 0 and info.st_gid == 0 and not TMPFS_ROOT.is_symlink(), "tmpfs root unsafe"); os.chmod(TMPFS_ROOT, 0o700)
    require(filesystem_type(TMPFS_ROOT) == "tmpfs", "encrypted staging root is not tmpfs")
    user = pwd.getpwnam(AUDIT_USER); staging = Path(tempfile.mkdtemp(prefix="d4e-", dir=TMPFS_ROOT))
    os.chown(staging, user.pw_uid, user.pw_gid); os.chmod(staging, 0o700)
    require(filesystem_type(staging) == "tmpfs", "encrypted staging directory is not tmpfs")
    return staging, user


def _hash_fd(fd: int) -> str:
    digest = hashlib.sha256(); os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk: break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET); return digest.hexdigest()


def decrypt_file(source: Path, expected_sha: str, destination: Path, user: pwd.struct_passwd) -> None:
    before = source.lstat(); require(stat.S_ISREG(before.st_mode) and not source.is_symlink(), "encrypted input changed type")
    flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0); src_fd = os.open(source, flags); dst_fd = -1
    try:
        opened = os.fstat(src_fd); require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino), "encrypted input changed during validation")
        require(_hash_fd(src_fd) == expected_sha, "encrypted input ciphertext SHA mismatch")
        dst_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        completed = subprocess.run([str(AGE), "--decrypt", "-i", str(AGE_IDENTITY)], stdin=src_fd, stdout=dst_fd, stderr=subprocess.PIPE, check=False, timeout=180)
        os.fsync(dst_fd); require(completed.returncode == 0, "age decrypt failed")
        closed = os.fstat(src_fd)
        require((closed.st_dev, closed.st_ino, closed.st_size, closed.st_mtime_ns, closed.st_ctime_ns) == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns), "encrypted input changed during decryption")
    finally:
        if dst_fd >= 0: os.close(dst_fd)
        os.close(src_fd)
    require(destination.is_file() and not destination.is_symlink() and destination.stat().st_size > 0, "decrypted archive missing or empty")
    with destination.open("rb") as handle: require(handle.read(2) == b"\x1f\x8b", "decrypted archive is not gzip")
    try:
        with tarfile.open(destination, "r:gz") as archive:
            for _ in archive: pass
    except (tarfile.TarError, OSError) as exc:
        raise D4EncryptedDispatchError("decrypted archive tar/gzip validation failed") from exc
    os.chown(destination, user.pw_uid, user.pw_gid); os.chmod(destination, 0o600)


def stage_v3(base: Any, staging: Path, user: pwd.struct_passwd, payload: Mapping[str, Any]):
    complete, roots, files, encrypted = validate_v3_request(base, payload)
    inputs = staging / "authorized-inputs"; base._make_private_dir(inputs, user); staged_roots = []; staged_files = []; evidence = []
    for index, (input_id, source) in enumerate(roots):
        dst = inputs / f"root-{index:02d}"; base._copy_authorized_tree(source, dst, user); staged_roots.append({"id": input_id, "path": str(dst)})
    for index, (input_id, source) in enumerate(files):
        suffix = ".tar.gz" if source.name.endswith(".tar.gz") else ".tgz"; dst = inputs / f"file-{index:02d}{suffix}"
        base._copy_regular_file(source, dst, user); staged_files.append({"id": input_id, "path": str(dst)})
    for index, (input_id, source, digest) in enumerate(encrypted):
        dst = inputs / f"encrypted-{index:02d}.tar.gz"; decrypt_file(source, digest, dst, user)
        staged_files.append({"id": input_id, "path": str(dst)}); evidence.append({"id": input_id, "ciphertext_sha256": digest})
    internal = {"schema_version": 2, "issue_number": ISSUE_NUMBER, "authoritative_source_set_complete": complete, "roots": staged_roots, "files": staged_files}
    request = staging / "execution-request.json"; request.write_text(json.dumps(internal, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chown(request, user.pw_uid, user.pw_gid); os.chmod(request, 0o600); return request, evidence


def strict_cleanup(path: Path) -> None:
    if not path.exists() and not path.is_symlink(): return
    shutil.rmtree(path); require(not path.exists() and not path.is_symlink(), "staging cleanup incomplete")


def _absolute(value: Any) -> bool:
    if isinstance(value, str): return value.startswith("/")
    if isinstance(value, Mapping): return any(_absolute(v) for v in value.values())
    if isinstance(value, (list, tuple)): return any(_absolute(v) for v in value)
    return False


def write_manifest(base: Any, export: Path, *, commit_sha: str, decision: str, fingerprint: str, request_sha256: str, d4_sha256: str, encrypted_inputs: list[dict[str, str]]) -> None:
    files = []
    for path in sorted(export.iterdir(), key=lambda p: p.name):
        if path.name == "dispatcher-evidence-manifest.json": continue
        require(path.name in {"diagnostic-result.json", "diagnostic-exit-code.txt"} and path.is_file() and not path.is_symlink(), "unexpected export member")
        files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": base.sha_file(path)})
    payload = {
        "schema_version": 2, "audit": AUDIT, "commit_sha": commit_sha, "decision": decision,
        "diagnostic_fingerprint": fingerprint, "request_bound": True, "request_sha256": request_sha256,
        "d4_sha256": d4_sha256, "d3_sha256": EXPECTED_D3_SHA256, "files": files, "sanitization_passed": True,
        "encrypted_input_count": len(encrypted_inputs), "encrypted_inputs": encrypted_inputs,
        "encrypted_decryption_tmpfs_only": bool(encrypted_inputs), "encrypted_plaintext_exported": False,
        "encrypted_plaintext_cleanup_passed": True, "age_identity_exported": False,
        "raw_evidence_exported": False, "raw_exception_exported": False, "network_acquisition_authorized": False,
        "archive_extraction_authorized": False, "source_or_corpus_mutation_authorized": False,
        "review_or_publication_write_authorized": False, "production_database_write_authorized": False,
        "production_deployment_authorized": False, "scheduler_systemd_canary_authorized": False,
        "destructive_cleanup_authorized": False, "newer_41_plus_41_substitution_authorized": False,
        "historical_recovery_binding_authorized": False, "irrecoverable_decision_recording_authorized": False,
    }
    require(not _absolute(payload), "manifest contains absolute path")
    (export / "dispatcher-evidence-manifest.json").write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
