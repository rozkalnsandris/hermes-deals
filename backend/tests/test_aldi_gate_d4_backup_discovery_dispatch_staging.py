from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "runner" / "aldi_gate_d4_backup_discovery_dispatch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_backup_discovery_dispatch_staging", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_user():
    return SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())


def no_chown(monkeypatch, module):
    monkeypatch.setattr(module.os, "chown", lambda *_args, **_kwargs: None)


def write_request(path: Path, root: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "issue_number": 631,
                "authoritative_source_set_complete": False,
                "roots": [{"id": "backup-root", "path": str(root)}],
                "files": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_root_owned_0700_parent_exact_authorized_child_is_staged_not_exposed(monkeypatch, tmp_path):
    module = load_module()
    no_chown(monkeypatch, module)

    protected_parent = tmp_path / "backups"
    protected_parent.mkdir(mode=0o700)
    source = protected_parent / "hermes-deals"
    source.mkdir(mode=0o700)
    releases = source / "releases"
    releases.mkdir()
    archive = releases / "candidate.tar.gz"
    archive.write_bytes(b"immutable-backup-bytes")
    os.chmod(protected_parent, 0o700)

    request = tmp_path / "request.json"
    write_request(request, source)
    monkeypatch.setattr(module, "REQUEST", request)

    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    staged_request = module.stage_authorized_request(staging, audit_user())
    rewritten = json.loads(staged_request.read_text(encoding="utf-8"))

    rewritten_root = Path(rewritten["roots"][0]["path"])
    assert rewritten_root != source
    assert staging in rewritten_root.parents
    assert (rewritten_root / "releases" / "candidate.tar.gz").read_bytes() == b"immutable-backup-bytes"
    assert str(source) not in staged_request.read_text(encoding="utf-8")
    assert rewritten["authoritative_source_set_complete"] is False
    assert rewritten["files"] == []


def test_staging_copies_only_explicit_root_and_not_sibling(monkeypatch, tmp_path):
    module = load_module()
    no_chown(monkeypatch, module)

    protected_parent = tmp_path / "backups"
    protected_parent.mkdir(mode=0o700)
    authorized = protected_parent / "hermes-deals"
    authorized.mkdir()
    (authorized / "allowed.tar.gz").write_bytes(b"allowed")
    sibling = protected_parent / "other-backups"
    sibling.mkdir()
    (sibling / "secret.tar.gz").write_bytes(b"must-not-be-staged")

    request = tmp_path / "request.json"
    write_request(request, authorized)
    monkeypatch.setattr(module, "REQUEST", request)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)

    staged_request = module.stage_authorized_request(staging, audit_user())
    rewritten = json.loads(staged_request.read_text(encoding="utf-8"))
    staged_root = Path(rewritten["roots"][0]["path"])

    assert (staged_root / "allowed.tar.gz").read_bytes() == b"allowed"
    assert not any(path.name == "secret.tar.gz" for path in staging.rglob("*"))


def test_staging_rejects_symlink_inside_authorized_root(monkeypatch, tmp_path):
    module = load_module()
    no_chown(monkeypatch, module)

    source = tmp_path / "hermes-deals"
    source.mkdir()
    outside = tmp_path / "outside.tar.gz"
    outside.write_bytes(b"outside")
    (source / "escape.tar.gz").symlink_to(outside)
    request = tmp_path / "request.json"
    write_request(request, source)
    monkeypatch.setattr(module, "REQUEST", request)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)

    with pytest.raises(module.DispatchError, match="contains symlink"):
        module.stage_authorized_request(staging, audit_user())


def test_staging_rejects_broad_or_traversing_root_before_copy(monkeypatch, tmp_path):
    module = load_module()
    no_chown(monkeypatch, module)
    request = tmp_path / "request.json"
    monkeypatch.setattr(module, "REQUEST", request)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)

    request.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "issue_number": 631,
                "authoritative_source_set_complete": False,
                "roots": [{"id": "bad", "path": "/"}],
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.DispatchError, match="too broad"):
        module.stage_authorized_request(staging, audit_user())

    request.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "issue_number": 631,
                "authoritative_source_set_complete": False,
                "roots": [{"id": "bad", "path": str(tmp_path / "x" / ".." / "y")}],
                "files": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.DispatchError, match="parent traversal"):
        module.stage_authorized_request(staging, audit_user())


def test_source_keeps_scanner_unprivileged_and_has_no_mount_acl_or_permission_relaxation_surface():
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"/usr/sbin/runuser", "-u", AUDIT_USER' in source
    assert "stage_authorized_request" in source
    for forbidden in (
        "chmod /opt/backups",
        "chown /opt/backups",
        "setfacl",
        "mount --bind",
        "os.seteuid",
        "sudo ",
    ):
        assert forbidden not in source
