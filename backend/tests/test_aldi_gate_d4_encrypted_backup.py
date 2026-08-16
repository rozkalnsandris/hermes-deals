from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import pwd
import shutil
import tarfile
import tempfile
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBase:
    @staticmethod
    def _resolve_original_root(value: Any) -> Path:
        path = Path(value); resolved = path.resolve(strict=True)
        if resolved != path or not path.is_dir() or path.is_symlink(): raise RuntimeError("bad root")
        return resolved

    @staticmethod
    def _resolve_original_file(value: Any) -> Path:
        path = Path(value); resolved = path.resolve(strict=True)
        if resolved != path or not path.is_file() or path.is_symlink() or not (path.name.endswith(".tar.gz") or path.name.endswith(".tgz")):
            raise RuntimeError("bad file")
        return resolved

    @staticmethod
    def _make_private_dir(path: Path, user: pwd.struct_passwd) -> None:
        path.mkdir(mode=0o700); os.chmod(path, 0o700)

    @staticmethod
    def _copy_regular_file(source: Path, destination: Path, user: pwd.struct_passwd) -> None:
        shutil.copyfile(source, destination); os.chmod(destination, 0o600)

    @classmethod
    def _copy_authorized_tree(cls, source: Path, destination: Path, user: pwd.struct_passwd) -> None:
        cls._make_private_dir(destination, user)
        for item in source.iterdir():
            if item.is_symlink(): raise RuntimeError("symlink")
            if item.is_dir(): cls._copy_authorized_tree(item, destination / item.name, user)
            elif item.is_file(): cls._copy_regular_file(item, destination / item.name, user)
            else: raise RuntimeError("type")

    @staticmethod
    def sha_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


def tar_gz_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "payload.tar.gz"
        source = Path(td) / "marker.txt"; source.write_text("legacy-evidence", encoding="utf-8")
        with tarfile.open(archive, "w:gz") as handle: handle.add(source, arcname="marker.txt")
        return archive.read_bytes()


def test_v3_validation_and_rejections(tmp_path: Path):
    support = load_module(ROOT / "tools/runner/aldi_gate_d4_encrypted_backup_support.py", "d4e_support_validation")
    root = tmp_path / "root"; root.mkdir(); plain = tmp_path / "plain.tar.gz"; plain.write_bytes(b"x")
    encrypted = tmp_path / "nightly.tar.gz.age"; encrypted.write_bytes(b"cipher")
    digest = hashlib.sha256(encrypted.read_bytes()).hexdigest()
    request = {
        "schema_version": 3, "issue_number": 631, "authoritative_source_set_complete": False,
        "roots": [{"id": "root", "path": str(root)}], "files": [{"id": "plain", "path": str(plain)}],
        "encrypted_files": [{"id": "nightly", "path": str(encrypted), "ciphertext_sha256": digest}],
    }
    complete, roots, files, encrypted_rows = support.validate_v3_request(FakeBase(), request)
    assert complete is False and len(roots) == len(files) == len(encrypted_rows) == 1

    bad_sha = json.loads(json.dumps(request)); bad_sha["encrypted_files"][0]["ciphertext_sha256"] = "0" * 63
    with pytest.raises(support.D4EncryptedDispatchError): support.validate_v3_request(FakeBase(), bad_sha)
    duplicate_id = json.loads(json.dumps(request)); duplicate_id["encrypted_files"][0]["id"] = "plain"
    with pytest.raises(support.D4EncryptedDispatchError): support.validate_v3_request(FakeBase(), duplicate_id)
    inside = root / "inside.tar.gz.age"; inside.write_bytes(b"z")
    overlap = {"schema_version": 3, "issue_number": 631, "authoritative_source_set_complete": False, "roots": [{"id": "root", "path": str(root)}], "files": [], "encrypted_files": [{"id": "e", "path": str(inside), "ciphertext_sha256": hashlib.sha256(b"z").hexdigest()}]}
    with pytest.raises(support.D4EncryptedDispatchError): support.validate_v3_request(FakeBase(), overlap)
    link = tmp_path / "link.tar.gz.age"; link.symlink_to(encrypted)
    symlinked = {"schema_version": 3, "issue_number": 631, "authoritative_source_set_complete": False, "roots": [], "files": [], "encrypted_files": [{"id": "e", "path": str(link), "ciphertext_sha256": digest}]}
    with pytest.raises(support.D4EncryptedDispatchError): support.validate_v3_request(FakeBase(), symlinked)


def test_decrypt_sha_gzip_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    support = load_module(ROOT / "tools/runner/aldi_gate_d4_encrypted_backup_support.py", "d4e_support_decrypt")
    ciphertext = tmp_path / "backup.tar.gz.age"; ciphertext.write_bytes(b"bound-ciphertext")
    plaintext = tmp_path / "plaintext.tar.gz"; plaintext.write_bytes(tar_gz_bytes())
    fake_age = tmp_path / "age"; fake_age.write_text("#!/bin/sh\ncat \"$FAKE_PLAINTEXT\"\n", encoding="utf-8"); fake_age.chmod(0o755)
    monkeypatch.setattr(support, "AGE", fake_age); monkeypatch.setenv("FAKE_PLAINTEXT", str(plaintext))
    user = pwd.getpwuid(os.getuid()); destination = tmp_path / "decrypted.tar.gz"
    support.decrypt_file(ciphertext, hashlib.sha256(ciphertext.read_bytes()).hexdigest(), destination, user)
    assert destination.read_bytes() == plaintext.read_bytes()
    with pytest.raises(support.D4EncryptedDispatchError):
        support.decrypt_file(ciphertext, "0" * 64, tmp_path / "wrong.tar.gz", user)
    failing = tmp_path / "age-fail"; failing.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8"); failing.chmod(0o755)
    monkeypatch.setattr(support, "AGE", failing)
    with pytest.raises(support.D4EncryptedDispatchError):
        support.decrypt_file(ciphertext, hashlib.sha256(ciphertext.read_bytes()).hexdigest(), tmp_path / "failed.tar.gz", user)


def test_tmpfs_rejection_and_strict_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    support = load_module(ROOT / "tools/runner/aldi_gate_d4_encrypted_backup_support.py", "d4e_support_tmpfs")
    monkeypatch.setattr(support, "filesystem_type", lambda path: "ext4")
    with pytest.raises(support.D4EncryptedDispatchError, match="/run is not tmpfs"):
        support.prepare_tmpfs_staging(FakeBase())
    staging = tmp_path / "staging"; staging.mkdir(); (staging / "plaintext.tar.gz").write_bytes(b"secret")
    support.strict_cleanup(staging); assert not staging.exists()
    staging.mkdir(); monkeypatch.setattr(support.shutil, "rmtree", lambda path: (_ for _ in ()).throw(OSError("blocked")))
    with pytest.raises(OSError): support.strict_cleanup(staging)


def test_manifest_is_sanitized_and_binds_ciphertext(tmp_path: Path):
    support = load_module(ROOT / "tools/runner/aldi_gate_d4_encrypted_backup_support.py", "d4e_support_manifest")
    (tmp_path / "diagnostic-result.json").write_text("{}", encoding="utf-8"); (tmp_path / "diagnostic-exit-code.txt").write_text("0\n", encoding="utf-8")
    support.write_manifest(FakeBase(), tmp_path, commit_sha="a" * 40, decision="NO_CANDIDATE_IN_DESIGNATED_ROOTS", fingerprint="b" * 64, request_sha256="c" * 64, d4_sha256="d" * 64, encrypted_inputs=[{"id": "nightly", "ciphertext_sha256": "e" * 64}])
    payload = json.loads((tmp_path / "dispatcher-evidence-manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2 and payload["encrypted_input_count"] == 1
    assert payload["encrypted_decryption_tmpfs_only"] is True and payload["encrypted_plaintext_exported"] is False
    assert payload["encrypted_plaintext_cleanup_passed"] is True and payload["age_identity_exported"] is False
    text = json.dumps(payload, sort_keys=True)
    assert "/etc/rpi5-backup" not in text and "/opt/backups" not in text and "plaintext.tar.gz" not in text


def test_dispatcher_failure_is_sanitized(tmp_path: Path):
    dispatcher = load_module(ROOT / "tools/runner/aldi_gate_d4_encrypted_backup_dispatch.py", "d4e_dispatch")
    dispatcher._failure(None, tmp_path, "encrypted_input_decryption", "age_decrypt_exit_1", RuntimeError("/secret/key"))
    payload = json.loads((tmp_path / "diagnostic-failure.json").read_text(encoding="utf-8")); text = json.dumps(payload)
    assert payload["failure_stage"] == "encrypted_input_decryption" and payload["reason_code"] == "age_decrypt_exit_1"
    assert "/secret/key" not in text and payload["raw_exception_exported"] is False and payload["raw_request_exported"] is False


def test_support_is_verified_before_import():
    dispatcher = load_module(ROOT / "tools/runner/aldi_gate_d4_encrypted_backup_dispatch.py", "d4e_dispatch_order")
    source = inspect.getsource(dispatcher._load_support)
    assert source.index("_sha_file(SUPPORT)") < source.index("exec_module")


def test_v4_request_compatibility_and_blob_pins():
    v4 = load_module(ROOT / "tools/runner/install_aldi_gate_d4_backup_discovery_nonrewind_v4.py", "d4e_v4")
    base = v4.load_base(); original = base.validate_request_payload
    v1 = {"schema_version": 1, "issue_number": 631, "authoritative_source_set_complete": False, "roots": [{"id": "r", "path": "/opt/backup-a"}]}
    v2 = {"schema_version": 2, "issue_number": 631, "authoritative_source_set_complete": False, "roots": [], "files": [{"id": "f", "path": "/opt/backup-a.tar.gz"}]}
    v3 = {"schema_version": 3, "issue_number": 631, "authoritative_source_set_complete": False, "roots": [], "files": [], "encrypted_files": [{"id": "e", "path": "/opt/backups/rpi5_backup_x.tar.gz.age", "ciphertext_sha256": "a" * 64}]}
    v4.validate_request_payload_v4(base, original, v1); v4.validate_request_payload_v4(base, original, v2); v4.validate_request_payload_v4(base, original, v3)
    bad = json.loads(json.dumps(v3)); del bad["encrypted_files"][0]["ciphertext_sha256"]
    with pytest.raises(v4.RegistrationV4Error): v4.validate_request_payload_v4(base, original, bad)
    assert v4.EXPECTED_D4_BLOB == "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
    assert v4.EXPECTED_D3_BLOB == "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
    assert v4.EXPECTED_BASE_DISPATCHER_BLOB == "f76ab8dfa938162dea038a2ef981c9002d5382e5"
