from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "runner" / "install_aldi_gate_d4_backup_discovery_nonrewind.py"

SPEC = importlib.util.spec_from_file_location("install_aldi_gate_d4_backup_discovery_nonrewind_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_request(*, complete: bool = False) -> dict:
    return {
        "schema_version": 1,
        "issue_number": 631,
        "authoritative_source_set_complete": complete,
        "roots": [
            {"id": "nightly-backup", "path": "/opt/backups/hermes-deals"},
            {"id": "offline-copy", "path": "/srv/archive/hermes-deals"},
        ],
    }


def test_registration_is_pinned_to_exact_merged_runtime_and_blobs() -> None:
    assert MODULE.EXPECTED_TARGET_SHA == "c53665477a91a8b2b69cc5b63810c091c3072b8e"
    assert MODULE.EXPECTED_D4_BLOB == "90b4dcfc2b5d2c0062a7b66db6208e9fc5824989"
    assert MODULE.EXPECTED_D3_BLOB == "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
    assert MODULE.EXPECTED_DISPATCHER_BLOB == "dd3dd3945ba45c51dff1b34b2a282ca03db0090f"
    assert MODULE.EXPECTED_D3_SHA256 == "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"


def test_request_schema_accepts_only_explicit_bounded_roots() -> None:
    MODULE.validate_request_payload(valid_request())
    MODULE.validate_request_payload(valid_request(complete=True))


@pytest.mark.parametrize("path", ["/", "/home", "/home/andris", MODULE.EXHAUSTED_D3_ROOT])
def test_request_rejects_broad_or_already_exhausted_root(path: str) -> None:
    payload = valid_request()
    payload["roots"] = [{"id": "bad", "path": path}]
    with pytest.raises(MODULE.RegistrationError):
        MODULE.validate_request_payload(payload)


@pytest.mark.parametrize("path", ["relative/path", "/opt/a/../b", "/opt//backups", "/opt/backups/"])
def test_request_rejects_noncanonical_or_traversing_root(path: str) -> None:
    payload = valid_request()
    payload["roots"] = [{"id": "bad", "path": path}]
    with pytest.raises(MODULE.RegistrationError):
        MODULE.validate_request_payload(payload)


def test_request_rejects_duplicate_overlapping_or_excess_roots() -> None:
    payload = valid_request()
    payload["roots"] = [
        {"id": "a", "path": "/opt/backups/hermes"},
        {"id": "b", "path": "/opt/backups/hermes/nested"},
    ]
    with pytest.raises(MODULE.RegistrationError, match="overlap"):
        MODULE.validate_request_payload(payload)

    payload = valid_request()
    payload["roots"] = [{"id": f"r{i}", "path": f"/srv/backup-{i}"} for i in range(9)]
    with pytest.raises(MODULE.RegistrationError, match="root count"):
        MODULE.validate_request_payload(payload)


def test_request_validation_does_not_resolve_or_stat_backup_roots(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("registration request validation must not touch backup roots")

    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    MODULE.validate_request_payload(valid_request())


def test_register_runtime_writes_exact_false_authority_config(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    dispatch = tmp_path / "dispatcher"
    monkeypatch.setattr(MODULE, "CONFIG_DST", config)
    monkeypatch.setattr(MODULE, "DISPATCH_DST", dispatch)
    monkeypatch.setattr(MODULE, "install_sudoers", lambda: None)

    real_atomic = MODULE.atomic_root_write

    def local_atomic(path: Path, payload: bytes, mode: int) -> None:
        if path in {config, dispatch}:
            path.write_bytes(payload)
            path.chmod(mode)
            return
        real_atomic(path, payload, mode)

    monkeypatch.setattr(MODULE, "atomic_root_write", local_atomic)
    runtime = Path("/usr/local/libexec/hermes-deals-audits/aldi-gate-d4-backup-discovery") / MODULE.EXPECTED_TARGET_SHA
    dispatcher = b"fixed dispatcher\n"
    MODULE.register_runtime(
        MODULE.EXPECTED_TARGET_SHA,
        runtime,
        "a" * 64,
        MODULE.EXPECTED_D3_SHA256,
        dispatcher,
        "b" * 64,
    )
    payload = json.loads(config.read_text())
    assert payload["commit_sha"] == MODULE.EXPECTED_TARGET_SHA
    assert payload["request_sha256"] == "b" * 64
    assert payload["d3_sha256"] == MODULE.EXPECTED_D3_SHA256
    assert all(payload[flag] is False for flag in MODULE.AUTHORITY_FLAGS)


def test_source_does_not_embed_real_backup_roots_or_acquisition_surface() -> None:
    source = TOOL.read_text(encoding="utf-8")
    assert '"roots": [' not in source
    for forbidden in (
        "requests.",
        "urllib",
        "curl ",
        "wget ",
        ".extract(",
        "docker compose",
        "psql ",
        "alembic ",
        "git reset",
        "git checkout",
    ):
        assert forbidden not in source
    assert "validate_owner_request" in source
    assert "REQUEST_CONTENT_EXPORTED=false" in source
    assert "NON_REWIND_REGISTRATION=true" in source
