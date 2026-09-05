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


def valid_v2_request(*, roots: list[dict] | None = None, files: list[dict] | None = None) -> dict:
    return {
        "schema_version": 2,
        "issue_number": 631,
        "authoritative_source_set_complete": False,
        "roots": [] if roots is None else roots,
        "files": (
            [{"id": "legacy-a0a1", "path": "/home/andris/hermes-deals-aldi-a0a1-latest.tar.gz"}]
            if files is None
            else files
        ),
    }


def test_registration_is_pinned_to_exact_merged_v2_runtime_and_blobs() -> None:
    assert MODULE.EXPECTED_TARGET_SHA == "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
    assert MODULE.EXPECTED_D4_BLOB == "f8ec4abb3f0c416335144f0f18e8a7c323353f4a"
    assert MODULE.EXPECTED_D3_BLOB == "4c4432baa048011ac9dfd427d8e2a0d0b4cfd2a7"
    assert MODULE.EXPECTED_DISPATCHER_BLOB == "2e7f8dd4f5b0dece36403072b6dfa6dab3aadd35"
    assert MODULE.EXPECTED_D3_SHA256 == "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"


def test_request_schema_keeps_v1_root_only_compatibility() -> None:
    MODULE.validate_request_payload(valid_request())
    MODULE.validate_request_payload(valid_request(complete=True))


def test_request_schema_accepts_v2_root_file_and_mixed_inputs() -> None:
    MODULE.validate_request_payload(valid_v2_request())
    MODULE.validate_request_payload(
        valid_v2_request(roots=[{"id": "offline", "path": "/srv/archive/hermes-deals"}], files=[])
    )
    MODULE.validate_request_payload(
        valid_v2_request(
            roots=[{"id": "offline", "path": "/srv/archive/hermes-deals"}],
            files=[{"id": "legacy", "path": "/home/andris/hermes-deals-aldi-a0a1-latest.tgz"}],
        )
    )


def test_v2_request_requires_at_least_one_bounded_input_and_max_eight_total() -> None:
    with pytest.raises(MODULE.RegistrationError, match="at least one"):
        MODULE.validate_request_payload(valid_v2_request(roots=[], files=[]))

    payload = valid_v2_request(
        roots=[{"id": f"r{i}", "path": f"/srv/backup-{i}"} for i in range(4)],
        files=[{"id": f"f{i}", "path": f"/home/andris/legacy-{i}.tar.gz"} for i in range(5)],
    )
    with pytest.raises(MODULE.RegistrationError, match="input count"):
        MODULE.validate_request_payload(payload)


def test_v2_request_uses_one_id_namespace_and_unique_paths() -> None:
    payload = valid_v2_request(
        roots=[{"id": "same", "path": "/srv/archive/hermes-deals"}],
        files=[{"id": "same", "path": "/home/andris/legacy.tar.gz"}],
    )
    with pytest.raises(MODULE.RegistrationError, match="duplicate request input id"):
        MODULE.validate_request_payload(payload)

    payload = valid_v2_request(
        roots=[],
        files=[
            {"id": "a", "path": "/home/andris/legacy.tar.gz"},
            {"id": "b", "path": "/home/andris/legacy.tar.gz"},
        ],
    )
    with pytest.raises(MODULE.RegistrationError, match="duplicate request file path"):
        MODULE.validate_request_payload(payload)


def test_v2_request_rejects_unsupported_noncanonical_or_root_covered_files() -> None:
    for path in (
        "relative.tar.gz",
        "/home/andris/a/../legacy.tar.gz",
        "/home/andris//legacy.tar.gz",
        "/home/andris/legacy.zip",
        f"{MODULE.EXHAUSTED_D3_ROOT}/legacy.tar.gz",
    ):
        payload = valid_v2_request(roots=[], files=[{"id": "bad", "path": path}])
        with pytest.raises(MODULE.RegistrationError):
            MODULE.validate_request_payload(payload)

    payload = valid_v2_request(
        roots=[{"id": "archive", "path": "/srv/archive"}],
        files=[{"id": "legacy", "path": "/srv/archive/legacy.tar.gz"}],
    )
    with pytest.raises(MODULE.RegistrationError, match="inside a designated root"):
        MODULE.validate_request_payload(payload)


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


def test_request_rejects_duplicate_overlapping_or_excess_v1_roots() -> None:
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


def test_request_validation_does_not_resolve_or_stat_backup_inputs(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("registration request validation must not touch backup inputs")

    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    MODULE.validate_request_payload(valid_request())
    MODULE.validate_request_payload(valid_v2_request())


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


def test_source_does_not_embed_real_backup_inputs_or_acquisition_surface() -> None:
    source = TOOL.read_text(encoding="utf-8")
    assert '"roots": [' not in source
    assert '"files": [' not in source
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
