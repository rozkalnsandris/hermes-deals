#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
from types import ModuleType
from typing import Any, Mapping

BASE_INSTALLER_PATH = "tools/runner/install_aldi_gate_d4_backup_discovery_nonrewind.py"
BASE_DISPATCHER_PATH = "tools/runner/aldi_gate_d4_backup_discovery_dispatch.py"
SUPPORT_PATH = "tools/runner/aldi_gate_d4_encrypted_backup_support.py"
DISPATCHER_PATH = "tools/runner/aldi_gate_d4_encrypted_backup_dispatch.py"
INSTALLER_PATH = "tools/runner/install_aldi_gate_d4_backup_discovery_nonrewind_v4.py"
D4_PATH = "tools/aldi_gate_d4_backup_discovery.py"
D3_PATH = "tools/aldi_gate_d3_recovery_inventory.py"
EXPECTED_TARGET_SHA = "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
EXPECTED_D4_BLOB = "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
EXPECTED_D3_BLOB = "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
EXPECTED_BASE_INSTALLER_BLOB = "de9048513e26c6de49d7c8ee4db4eb9e1bd6bbf1"
EXPECTED_BASE_DISPATCHER_BLOB = "f76ab8dfa938162dea038a2ef981c9002d5382e5"
EXPECTED_SUPPORT_BLOB = "0cab85917eadb26e529bfb68c9a4d0fea98fbe5d"
EXPECTED_DISPATCHER_BLOB = "3ed1fc20b877252c07c5757ce0cf348cb3a1ada3"
EXPECTED_SUPPORT_SHA256 = "247ce8db1de0de2e26b3bc0afd839646de71ef0b6a3a5f1bb8d30b3f7a6f279c"
EXPECTED_BASE_DISPATCHER_SHA256 = "894d8e60179552abf589577cd305ebc92427b1d0746955b15b1eb553e6961723"
BASE_FILE = Path(__file__).with_name("install_aldi_gate_d4_backup_discovery_nonrewind.py")
AGE = Path("/usr/bin/age")
AGE_IDENTITY = Path("/etc/rpi5-backup/age.key")
SUPPORT_DST = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery-d4e-support.py")
BASE_DISPATCH_DIR = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery-dispatch-base")
BASE_DISPATCH_DST = BASE_DISPATCH_DIR / f"{EXPECTED_BASE_DISPATCHER_BLOB}.py"
REGISTERED_AGE_SHA256 = ""


class RegistrationV4Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition: raise RegistrationV4Error(message)


def load_base() -> ModuleType:
    require(BASE_FILE.is_file() and not BASE_FILE.is_symlink(), "base installer missing or unsafe")
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_registration_base_v2_for_v4", BASE_FILE)
    require(spec is not None and spec.loader is not None, "base installer import unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    require(module.EXPECTED_TARGET_SHA == EXPECTED_TARGET_SHA, "base target pin drift")
    require(module.EXPECTED_D4_BLOB == EXPECTED_D4_BLOB, "base D4 pin drift")
    require(module.EXPECTED_D3_BLOB == EXPECTED_D3_BLOB, "base D3 pin drift")
    return module


def _text(base: Any, *args: str) -> str:
    return base.audit_git(*args).stdout.decode().strip()


def validate_source_repo(base: Any, target_sha: str):
    require(target_sha == EXPECTED_TARGET_SHA, "target SHA is not reviewed Gate D4 runtime SHA")
    before = base.index_snapshot()
    require(_text(base, "branch", "--show-current") == "main", "audit repo branch mismatch")
    head = _text(base, "rev-parse", "HEAD"); require(len(head) == 40, "audit repo HEAD invalid")
    require(base.audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b"", "audit repo dirty")
    target = _text(base, "rev-parse", "--verify", f"{target_sha}^{{commit}}"); require(target == target_sha, "reviewed target unavailable")
    ancestry = base.audit_git("merge-base", "--is-ancestor", target_sha, head, check=False)
    require(ancestry.returncode == 0 and not ancestry.stderr, "reviewed target is not an ancestor of audit repo HEAD")
    for path, blob in ((D4_PATH, EXPECTED_D4_BLOB), (D3_PATH, EXPECTED_D3_BLOB)):
        require(_text(base, "rev-parse", f"{target_sha}:{path}") == blob, f"reviewed Git blob mismatch: {path}")
    for path, blob in (
        (BASE_INSTALLER_PATH, EXPECTED_BASE_INSTALLER_BLOB),
        (BASE_DISPATCHER_PATH, EXPECTED_BASE_DISPATCHER_BLOB),
        (SUPPORT_PATH, EXPECTED_SUPPORT_BLOB),
        (DISPATCHER_PATH, EXPECTED_DISPATCHER_BLOB),
    ):
        require(_text(base, "rev-parse", f"HEAD:{path}") == blob, f"current Git blob mismatch: {path}")
    installer_blob = _text(base, "rev-parse", f"HEAD:{INSTALLER_PATH}"); require(installer_blob, "v4 installer blob unavailable")
    require(base.audit_git("cat-file", "blob", installer_blob).stdout == Path(__file__).read_bytes(), "v4 installer working-tree identity drift")
    require(base.index_snapshot() == before, "audit repo index changed during source validation")
    return before, head


def _canonical_encrypted(base: Any, value: Any) -> str:
    normalized = base._canonical_absolute_string(value, kind="encrypted file")
    require(normalized.endswith(".tar.gz.age"), "encrypted backup file suffix invalid")
    exhausted = PurePosixPath(base.EXHAUSTED_D3_ROOT); path = PurePosixPath(normalized)
    require(path != exhausted and exhausted not in path.parents, "Gate D3 state root was already covered")
    return normalized


def validate_request_payload_v4(base: Any, original: Any, payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") in {1, 2}:
        original(payload); return
    require(payload.get("schema_version") == 3, "request schema mismatch")
    require(set(payload) == {"schema_version", "issue_number", "authoritative_source_set_complete", "roots", "files", "encrypted_files"}, "request fields mismatch")
    require(payload.get("issue_number") == 631 and isinstance(payload.get("authoritative_source_set_complete"), bool), "request identity invalid")
    roots = payload.get("roots"); files = payload.get("files"); encrypted = payload.get("encrypted_files")
    require(isinstance(roots, list) and isinstance(files, list) and isinstance(encrypted, list), "request input lists invalid")
    require(roots or files or encrypted, "at least one explicit backup input is required")
    require(len(roots) + len(files) + len(encrypted) <= base.MAX_INPUTS, "request input count invalid")
    ids: set[str] = set(); root_paths: list[PurePosixPath] = []; file_paths: set[PurePosixPath] = set(); encrypted_paths: set[PurePosixPath] = set()
    for row in roots:
        require(isinstance(row, Mapping) and set(row) == {"id", "path"}, "request root entry invalid")
        base._validate_input_id(row.get("id"), ids); path = PurePosixPath(base._canonical_root_string(row.get("path")))
        require(path not in root_paths, "duplicate request root path")
        for existing in root_paths: require(path not in existing.parents and existing not in path.parents, "request roots must not overlap")
        root_paths.append(path)
    for row in files:
        require(isinstance(row, Mapping) and set(row) == {"id", "path"}, "request file entry invalid")
        base._validate_input_id(row.get("id"), ids); path = PurePosixPath(base._canonical_file_string(row.get("path")))
        require(path not in file_paths and all(root not in path.parents for root in root_paths), "request file path invalid or overlaps root")
        file_paths.add(path)
    for row in encrypted:
        require(isinstance(row, Mapping) and set(row) == {"id", "path", "ciphertext_sha256"}, "request encrypted file entry invalid")
        base._validate_input_id(row.get("id"), ids); path = PurePosixPath(_canonical_encrypted(base, row.get("path")))
        digest = row.get("ciphertext_sha256"); require(isinstance(digest, str) and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest), "encrypted ciphertext SHA invalid")
        require(path not in encrypted_paths and path not in file_paths and all(root not in path.parents for root in root_paths), "encrypted file path invalid or overlaps root")
        encrypted_paths.add(path)


def safe_age(base: Any) -> str:
    require(base.regular_root_file(AGE, 0o755) or base.regular_root_file(AGE, 0o555), "age executable missing or unsafe")
    require(base.regular_root_file(AGE_IDENTITY, 0o600), "age identity missing or unsafe")
    return base.sha_file(AGE)


def register_runtime_v4(base: Any, target_sha: str, runtime: Path, d4_sha: str, d3_sha: str, dispatcher: bytes, request_sha: str) -> str:
    global REGISTERED_AGE_SHA256
    dispatcher_sha = base.sha_bytes(dispatcher)
    support = base.read_exact_blob(EXPECTED_SUPPORT_BLOB); base_dispatch = base.read_exact_blob(EXPECTED_BASE_DISPATCHER_BLOB)
    require(base.sha_bytes(support) == EXPECTED_SUPPORT_SHA256, "D4E support SHA mismatch")
    require(base.sha_bytes(base_dispatch) == EXPECTED_BASE_DISPATCHER_SHA256, "base dispatcher support SHA mismatch")
    REGISTERED_AGE_SHA256 = safe_age(base)
    base.normalize_root_dir(BASE_DISPATCH_DIR)
    base.atomic_root_write(BASE_DISPATCH_DST, base_dispatch, 0o444)
    base.atomic_root_write(SUPPORT_DST, support, 0o444)
    base.atomic_root_write(base.DISPATCH_DST, dispatcher, 0o755)
    base.install_sudoers()
    config: dict[str, Any] = {
        "schema_version": 2, "audit": base.AUDIT, "commit_sha": target_sha,
        "d4_file": str(runtime / "aldi_gate_d4_backup_discovery.py"), "d4_sha256": d4_sha,
        "d3_file": str(runtime / "aldi_gate_d3_recovery_inventory.py"), "d3_sha256": d3_sha,
        "request_file": str(base.REQUEST_DST), "request_sha256": request_sha,
        "dispatcher_sha256": dispatcher_sha, "age_file": str(AGE), "age_sha256": REGISTERED_AGE_SHA256,
    }
    config.update({flag: False for flag in base.AUTHORITY_FLAGS})
    base.atomic_root_write(base.CONFIG_DST, (json.dumps(config, indent=2, sort_keys=True) + "\n").encode(), 0o600)
    return dispatcher_sha


def main() -> int:
    base = load_base(); original_validate = base.validate_request_payload
    base.EXPECTED_DISPATCHER_BLOB = EXPECTED_DISPATCHER_BLOB
    base.validate_source_repo = lambda target_sha: validate_source_repo(base, target_sha)
    base.validate_request_payload = lambda payload: validate_request_payload_v4(base, original_validate, payload)
    base.register_runtime = lambda target_sha, runtime, d4_sha, d3_sha, dispatcher, request_sha: register_runtime_v4(base, target_sha, runtime, d4_sha, d3_sha, dispatcher, request_sha)
    rc = int(base.main())
    if rc == 0:
        print(f"BASE_DISPATCHER_GIT_BLOB={EXPECTED_BASE_DISPATCHER_BLOB}")
        print(f"D4E_SUPPORT_GIT_BLOB={EXPECTED_SUPPORT_BLOB}")
        print(f"D4E_SUPPORT_SHA256={EXPECTED_SUPPORT_SHA256}")
        print(f"AGE_SHA256={REGISTERED_AGE_SHA256}")
        print("AGE_IDENTITY_CONTENT_EXPORTED=false")
        print("REAL_BACKUP_DECRYPTION_EXECUTED=false")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
