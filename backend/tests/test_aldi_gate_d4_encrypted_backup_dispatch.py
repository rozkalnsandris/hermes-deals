from __future__ import annotations

import gzip
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "runner" / "aldi_gate_d4_encrypted_backup_dispatch.py"
CONTRACT = ROOT / "tools" / "runner" / "aldi_gate_d4_encrypted_contract.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_encrypted_backup_dispatch_tested", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_binds_only_exact_encrypted_files_and_ciphertext_sha(monkeypatch, tmp_path):
    module = load_module()
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    encrypted = backup_root / "rpi5_backup_2026-08-16_02-00-00.tar.gz.age"
    encrypted.write_bytes(b"ciphertext")
    encrypted.chmod(0o600)
    request = tmp_path / "request.json"
    payload = {
        "schema_version": 1,
        "issue_number": 679,
        "parent_issue_number": 631,
        "encrypted_files": [{"id": "nightly-01", "path": str(encrypted), "ciphertext_sha256": "a" * 64}],
    }
    request.write_text(json.dumps(payload), encoding="utf-8")
    request.chmod(0o600)
    monkeypatch.setattr(module, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(module, "REQUEST", request)
    monkeypatch.setattr(module, "sha_file", lambda path: "b" * 64 if path == request else "a" * 64)
    monkeypatch.setattr(module, "regular_root_file", lambda path, mode=None: path in {request, encrypted} and mode == 0o600)

    _payload, rows = module.load_request({"request_sha256": "b" * 64})
    assert rows == [("nightly-01", encrypted, "a" * 64)]


def test_request_rejects_path_outside_exact_backup_root(monkeypatch, tmp_path):
    module = load_module()
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    outside = tmp_path / "rpi5_backup_2026-08-16_02-00-00.tar.gz.age"
    outside.write_bytes(b"ciphertext")
    outside.chmod(0o600)
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "schema_version": 1,
        "issue_number": 679,
        "parent_issue_number": 631,
        "encrypted_files": [{"id": "nightly-01", "path": str(outside), "ciphertext_sha256": "a" * 64}],
    }), encoding="utf-8")
    request.chmod(0o600)
    monkeypatch.setattr(module, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(module, "REQUEST", request)
    monkeypatch.setattr(module, "sha_file", lambda _path: "b" * 64)
    monkeypatch.setattr(module, "regular_root_file", lambda path, mode=None: path == request)
    with pytest.raises(module.EncryptedDispatchError, match="exact /opt/backups file"):
        module.load_request({"request_sha256": "b" * 64})


def test_request_rejects_invalid_ciphertext_sha(monkeypatch, tmp_path):
    module = load_module()
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    encrypted = backup_root / "rpi5_backup_2026-08-16_02-00-00.tar.gz.age"
    encrypted.write_bytes(b"x")
    request = tmp_path / "request.json"
    request.write_text(json.dumps({
        "schema_version": 1,
        "issue_number": 679,
        "parent_issue_number": 631,
        "encrypted_files": [{"id": "nightly-01", "path": str(encrypted), "ciphertext_sha256": "bad"}],
    }), encoding="utf-8")
    monkeypatch.setattr(module, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(module, "REQUEST", request)
    monkeypatch.setattr(module, "sha_file", lambda _path: "b" * 64)
    monkeypatch.setattr(module, "regular_root_file", lambda _path, _mode=None: True)
    with pytest.raises(module.EncryptedDispatchError, match="ciphertext SHA invalid"):
        module.load_request({"request_sha256": "b" * 64})


def test_prepare_tmpfs_fails_closed_when_parent_not_tmpfs(monkeypatch, tmp_path):
    module = load_module()
    monkeypatch.setattr(module, "TMPFS_PARENT", tmp_path)
    monkeypatch.setattr(module, "mount_fstype", lambda _path: "ext4")
    with pytest.raises(module.EncryptedDispatchError, match="not tmpfs"):
        module.prepare_tmpfs(SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()), 1024)


def test_decrypt_one_uses_open_fd_verifies_sha_and_emits_gzip_only(monkeypatch, tmp_path):
    module = load_module()
    source = tmp_path / "cipher.age"
    source.write_bytes(b"immutable-ciphertext")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    expected_sha = module.hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(module.os, "chown", lambda *_args: None)

    def fake_run(args, **kwargs):
        assert args[-1].startswith("/proc/self/fd/")
        assert kwargs["pass_fds"]
        kwargs["stdout"].write(gzip.compress(b"tar-ish"))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    destination = module.decrypt_one(Path("/usr/bin/age"), SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()), "nightly-01", source, expected_sha, run_dir)
    assert destination.read_bytes().startswith(b"\x1f\x8b")
    assert destination.stat().st_mode & 0o777 == 0o600


def test_decrypt_one_wrong_sha_does_not_leave_plaintext(monkeypatch, tmp_path):
    module = load_module()
    source = tmp_path / "cipher.age"
    source.write_bytes(b"ciphertext")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(module.EncryptedDispatchError, match="ciphertext SHA mismatch"):
        module.decrypt_one(Path("/usr/bin/age"), SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()), "nightly-01", source, "0" * 64, run_dir)
    assert not (run_dir / "nightly-01.tar.gz").exists()


def test_validate_result_rejects_irrecoverable_or_absolute_path():
    module = load_module()
    base = {
        "schema_version": 1,
        "mode": "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY",
        "issue_number": 631,
        "request_schema_version": 2,
        "decision": "NO_CANDIDATE_IN_DESIGNATED_ROOTS",
        "authoritative_source_set_complete": False,
        "designated_root_count": 0,
        "designated_file_count": 1,
        "designated_input_count": 1,
        "provenance_binding_complete": False,
        "historical_recovery_authorized": False,
        "irrecoverable_decision_recorded": False,
        "complete_recovery_source_count": 0,
        "distinct_complete_identity_count": 0,
        "complete_identities": [],
        "plausible_recovery_sources": [],
        "next_step": "authorize_additional_explicit_backup_inputs_or_mark_source_set_complete",
        "safety": {
            "explicit_inputs_only": True,
            "explicit_roots_only": False,
            "exact_file_allowlist_enabled": True,
            "strict_49_plus_41_frozen_contract_unchanged": True,
            "raw_page_bytes_exported": False,
        },
    }
    base["diagnostic_fingerprint"] = module.hashlib.sha256(module.canonical_bytes(base)).hexdigest()
    module.validate_result(base, 1)
    bad = dict(base)
    bad["decision"] = "READY_FOR_IRRECOVERABLE_DECISION"
    with pytest.raises(module.EncryptedDispatchError, match="unsupported"):
        module.validate_result(bad, 1)
    leaked = dict(base)
    leaked["leak"] = "/opt/backups/secret"
    leaked_source = dict(leaked)
    leaked_source.pop("diagnostic_fingerprint", None)
    leaked["diagnostic_fingerprint"] = module.hashlib.sha256(module.canonical_bytes(leaked_source)).hexdigest()
    with pytest.raises(module.EncryptedDispatchError, match="absolute path"):
        module.validate_result(leaked, 1)


def test_source_has_no_persistent_plaintext_or_backup_permission_workaround():
    source = SCRIPT.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")
    assert "TMPFS_PARENT=Path('/dev/shm')" in contract
    assert "AGE_KEY=Path('/etc/rpi5-backup/age.key')" in contract
    for forbidden in ("extractall(", "setfacl", "mount --bind", "chmod /opt/backups", "chown /opt/backups", "/tmp/hermes"):
        assert forbidden not in source


def test_manifest_exports_hashes_not_paths_or_plaintext(tmp_path):
    module = load_module()
    result = {"decision": "NO_CANDIDATE_IN_DESIGNATED_ROOTS", "diagnostic_fingerprint": "f" * 64}
    module.write_manifest(
        tmp_path,
        commit_sha=module.EXPECTED_TARGET_SHA,
        request_sha="a" * 64,
        d4_sha="b" * 64,
        result=result,
        encrypted_rows=[("nightly-01", Path("/opt/backups/rpi5_backup_secret.tar.gz.age"), "c" * 64)],
    )
    payload = json.loads((tmp_path / "dispatcher-evidence-manifest.json").read_text())
    assert payload["encrypted_inputs"] == [{"id": "nightly-01", "ciphertext_sha256": "c" * 64}]
    serialized = json.dumps(payload)
    assert "/opt/backups" not in serialized
    assert payload["plaintext_exported"] is False
    assert payload["age_identity_exported"] is False
