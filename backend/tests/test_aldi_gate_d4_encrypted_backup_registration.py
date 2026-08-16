from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "runner" / "install_aldi_gate_d4_encrypted_backup_nonrewind.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_encrypted_registration_tested", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_validator_requires_exact_encrypted_shape(monkeypatch, tmp_path):
    module = load_module()
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    encrypted = backup_root / "rpi5_backup_2026-08-16_02-00-00.tar.gz.age"
    encrypted.write_bytes(b"cipher")
    monkeypatch.setattr(module, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(module, "regular_root_file", lambda path, mode: path == encrypted and mode == 0o600)
    monkeypatch.setattr(module, "sha_file", lambda path: "a" * 64 if path == encrypted else "x")
    rows = module.validate_request_payload({
        "schema_version": 1,
        "issue_number": 679,
        "parent_issue_number": 631,
        "encrypted_files": [{"id": "nightly-01", "path": str(encrypted), "ciphertext_sha256": "a" * 64}],
    })
    assert rows[0][0] == "nightly-01"


def test_request_validator_rejects_duplicate_ids(monkeypatch, tmp_path):
    module = load_module()
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    files = []
    for idx in range(2):
        path = backup_root / f"rpi5_backup_2026-08-1{idx}_02-00-00.tar.gz.age"
        path.write_bytes(b"cipher")
        files.append(path)
    monkeypatch.setattr(module, "BACKUP_ROOT", backup_root)
    monkeypatch.setattr(module, "regular_root_file", lambda _path, _mode: True)
    monkeypatch.setattr(module, "sha_file", lambda _path: "a" * 64)
    with pytest.raises(module.RegistrationError, match="input id"):
        module.validate_request_payload({
            "schema_version": 1,
            "issue_number": 679,
            "parent_issue_number": 631,
            "encrypted_files": [
                {"id": "dup", "path": str(files[0]), "ciphertext_sha256": "a" * 64},
                {"id": "dup", "path": str(files[1]), "ciphertext_sha256": "a" * 64},
            ],
        })


def test_source_pins_reviewed_d4_d3_and_dispatcher():
    source = SCRIPT.read_text(encoding="utf-8")
    for value in (
        "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e",
        "f8ec4abb3f0c416335144f0f18e8a7c323353f4a",
        "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7",
        "efe99cd59f04df53b62b47dc83fe6afc4c46f57c",
        "ad2258201b94299d7ffdfa2a5b1841c4c150c8a5",
        "/etc/rpi5-backup/age.key",
        "DECRYPTION_EXECUTED=false",
    ):
        assert value in source
