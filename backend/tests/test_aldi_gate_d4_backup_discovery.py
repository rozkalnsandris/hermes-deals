from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "aldi_gate_d4_backup_discovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_backup_discovery", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def request(*roots: Path, complete: bool = False):
    return {
        "schema_version": 1,
        "issue_number": 631,
        "authoritative_source_set_complete": complete,
        "roots": [{"id": f"backup-{index}", "path": str(path)} for index, path in enumerate(roots, 1)],
    }


def request_v2(*roots: Path, files: tuple[Path, ...] = (), complete: bool = False):
    return {
        "schema_version": 2,
        "issue_number": 631,
        "authoritative_source_set_complete": complete,
        "roots": [{"id": f"root-{index}", "path": str(path)} for index, path in enumerate(roots, 1)],
        "files": [{"id": f"file-{index}", "path": str(path)} for index, path in enumerate(files, 1)],
    }


def inventory(*identities: str):
    sources = [
        {
            "kind": "directory",
            "source": f"candidate-{index}/raw/page-images",
            "identity_sha256": identity,
        }
        for index, identity in enumerate(identities, 1)
    ]
    return {
        "decision": "NO_RECOVERY_CANDIDATE" if not identities else "RECOVERY_CANDIDATE_FOUND",
        "state_root": ".",
        "manifest_count": 0,
        "directory_candidate_count": len(sources),
        "archive_count": 0,
        "complete_recovery_source_count": len(sources),
        "distinct_complete_identity_count": len(set(identities)),
        "manifests": [],
        "directory_candidates": [],
        "archives": [],
        "complete_recovery_sources": sources,
        "complete_identities": sorted(set(identities)),
    }


def archive_inventory(path: str, *identities: str, safe: bool = True, is_a21: bool = False):
    return {
        "path": path,
        "sha256": "f" * 64,
        "is_a21_archive": is_a21,
        "safe": safe,
        "unsafe_reason": None if safe else "tar_open_failed",
        "manifest_member_count": 1 if identities else 0,
        "complete_49_plus_41_count": len(set(identities)),
        "complete_identities": sorted(set(identities)),
    }


def install_fake_d3(monkeypatch, module, by_root_name=None, by_file_name=None):
    by_root_name = by_root_name or {}
    by_file_name = by_file_name or {}

    def build_inventory(root):
        return by_root_name[root.name]

    def inspect_archive(path, root):
        assert root == path.parent
        return by_file_name[path.name]

    monkeypatch.setattr(
        module,
        "_load_d3_module",
        lambda: SimpleNamespace(build_inventory=build_inventory, archive_inventory=inspect_archive),
    )


def test_v1_no_candidate_is_not_irrecoverable_without_complete_source_set(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    install_fake_d3(monkeypatch, module, {"backup": inventory()})

    result = module.build_discovery(request(backup))

    assert result["decision"] == "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
    assert result["irrecoverable_decision_recorded"] is False
    assert result["authoritative_source_set_complete"] is False
    assert result["request_schema_version"] == 1
    assert result["designated_file_count"] == 0
    assert result["safety"]["explicit_roots_only"] is True


def test_v1_complete_source_set_can_only_become_ready_for_separate_irrecoverable_decision(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    install_fake_d3(monkeypatch, module, {"backup": inventory()})

    result = module.build_discovery(request(backup, complete=True))

    assert result["decision"] == "READY_FOR_IRRECOVERABLE_DECISION"
    assert result["irrecoverable_decision_recorded"] is False
    assert result["historical_recovery_authorized"] is False


def test_one_root_identity_is_only_plausible_until_independent_provenance_binding(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    identity = "a" * 64
    install_fake_d3(monkeypatch, module, {"backup": inventory(identity)})

    result = module.build_discovery(request(backup))

    assert result["decision"] == "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    assert result["complete_identities"] == [identity]
    assert result["provenance_binding_complete"] is False
    row = result["plausible_recovery_sources"][0]
    assert row["root_id"] == "backup-1"
    assert row["input_id"] == "backup-1"
    assert row["input_kind"] == "root"
    assert row["provenance_status"] == "unbound_requires_gate_d4_binding"


def test_same_identity_in_multiple_roots_is_not_false_ambiguity(tmp_path, monkeypatch):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    identity = "b" * 64
    install_fake_d3(monkeypatch, module, {"first": inventory(identity), "second": inventory(identity)})

    result = module.build_discovery(request(first, second))

    assert result["decision"] == "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    assert result["distinct_complete_identity_count"] == 1
    assert result["complete_recovery_source_count"] == 2


def test_distinct_root_identities_fail_closed_as_ambiguous(tmp_path, monkeypatch):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    install_fake_d3(monkeypatch, module, {"first": inventory("a" * 64), "second": inventory("b" * 64)})

    result = module.build_discovery(request(first, second))

    assert result["decision"] == "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES"
    assert result["distinct_complete_identity_count"] == 2


def test_v2_exact_file_inventory_does_not_walk_parent_directory(tmp_path, monkeypatch):
    module = load_module()
    exact = tmp_path / "historical.tar.gz"
    exact.write_bytes(b"fixture")
    identity = "c" * 64
    install_fake_d3(
        monkeypatch,
        module,
        by_file_name={"historical.tar.gz": archive_inventory("historical.tar.gz", identity)},
    )

    result = module.build_discovery(request_v2(files=(exact,)))

    assert result["decision"] == "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    assert result["designated_root_count"] == 0
    assert result["designated_file_count"] == 1
    assert result["designated_input_count"] == 1
    assert result["root_reports"] == []
    assert result["file_reports"][0]["file_id"] == "file-1"
    assert result["file_reports"][0]["archive"]["path"] == "historical.tar.gz"
    row = result["plausible_recovery_sources"][0]
    assert row["file_id"] == "file-1"
    assert row["input_kind"] == "file"
    assert row["source"] == "historical.tar.gz"
    assert str(tmp_path) not in json.dumps(result, sort_keys=True)
    assert result["safety"]["explicit_inputs_only"] is True
    assert result["safety"]["explicit_roots_only"] is False
    assert result["safety"]["exact_file_allowlist_enabled"] is True


def test_v2_exact_file_without_candidate_is_not_irrecoverable(tmp_path, monkeypatch):
    module = load_module()
    exact = tmp_path / "historical.tgz"
    exact.write_bytes(b"fixture")
    install_fake_d3(
        monkeypatch,
        module,
        by_file_name={"historical.tgz": archive_inventory("historical.tgz")},
    )

    result = module.build_discovery(request_v2(files=(exact,)))

    assert result["decision"] == "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
    assert result["irrecoverable_decision_recorded"] is False
    assert result["next_step"] == "authorize_additional_explicit_backup_inputs_or_mark_source_set_complete"


def test_v2_complete_exact_file_source_set_only_becomes_ready_for_separate_irrecoverable_decision(tmp_path, monkeypatch):
    module = load_module()
    exact = tmp_path / "historical.tar.gz"
    exact.write_bytes(b"fixture")
    install_fake_d3(
        monkeypatch,
        module,
        by_file_name={"historical.tar.gz": archive_inventory("historical.tar.gz")},
    )

    result = module.build_discovery(request_v2(files=(exact,), complete=True))

    assert result["decision"] == "READY_FOR_IRRECOVERABLE_DECISION"
    assert result["irrecoverable_decision_recorded"] is False


def test_same_identity_across_root_and_exact_file_is_not_false_ambiguity(tmp_path, monkeypatch):
    module = load_module()
    root = tmp_path / "root"
    root.mkdir()
    exact = tmp_path / "historical.tar.gz"
    exact.write_bytes(b"fixture")
    identity = "d" * 64
    install_fake_d3(
        monkeypatch,
        module,
        {"root": inventory(identity)},
        {"historical.tar.gz": archive_inventory("historical.tar.gz", identity)},
    )

    result = module.build_discovery(request_v2(root, files=(exact,)))

    assert result["decision"] == "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    assert result["complete_recovery_source_count"] == 2
    assert result["distinct_complete_identity_count"] == 1


def test_distinct_identity_across_root_and_exact_file_fails_closed(tmp_path, monkeypatch):
    module = load_module()
    root = tmp_path / "root"
    root.mkdir()
    exact = tmp_path / "historical.tar.gz"
    exact.write_bytes(b"fixture")
    install_fake_d3(
        monkeypatch,
        module,
        {"root": inventory("a" * 64)},
        {"historical.tar.gz": archive_inventory("historical.tar.gz", "b" * 64)},
    )

    result = module.build_discovery(request_v2(root, files=(exact,)))

    assert result["decision"] == "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES"
    assert result["distinct_complete_identity_count"] == 2


def test_request_rejects_broad_duplicate_and_overlapping_roots(tmp_path):
    module = load_module()
    with pytest.raises(module.GateD4Error, match="too broad"):
        module.validate_request(request(Path("/")))

    first = tmp_path / "first"
    first.mkdir()
    payload = request(first)
    payload["roots"].append({"id": "backup-2", "path": str(first)})
    with pytest.raises(module.GateD4Error, match="duplicate backup root path"):
        module.validate_request(payload)

    child = first / "child"
    child.mkdir()
    with pytest.raises(module.GateD4Error, match="must not overlap"):
        module.validate_request(request(first, child))


def test_request_rejects_extra_fields_and_excessive_input_count(tmp_path):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    payload = request(backup)
    payload["unexpected"] = True
    with pytest.raises(module.GateD4Error, match="fields mismatch"):
        module.validate_request(payload)

    files = []
    for index in range(module.MAX_INPUTS + 1):
        path = tmp_path / f"archive-{index}.tar.gz"
        path.write_bytes(b"x")
        files.append(path)
    with pytest.raises(module.GateD4Error, match="too many backup inputs"):
        module.validate_request(request_v2(files=tuple(files)))


def test_v2_requires_at_least_one_explicit_input(tmp_path):
    module = load_module()
    with pytest.raises(module.GateD4Error, match="at least one explicit backup input"):
        module.validate_request(request_v2())


def test_request_rejects_symlink_root(tmp_path):
    module = load_module()
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(module.GateD4Error, match="unsafe"):
        module.validate_request(request(link))


def test_exact_file_rejects_non_archive_and_final_symlink(tmp_path):
    module = load_module()
    plain = tmp_path / "plain.txt"
    plain.write_bytes(b"x")
    with pytest.raises(module.GateD4Error, match="supported archive"):
        module.validate_request(request_v2(files=(plain,)))

    target = tmp_path / "target.tar.gz"
    target.write_bytes(b"x")
    link = tmp_path / "link.tar.gz"
    link.symlink_to(target)
    with pytest.raises(module.GateD4Error, match="unsafe"):
        module.validate_request(request_v2(files=(link,)))


def test_exact_file_rejects_ancestor_symlink(tmp_path):
    module = load_module()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    exact = real_dir / "historical.tar.gz"
    exact.write_bytes(b"x")
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(module.GateD4Error, match="must not contain symlinks"):
        module.validate_request(request_v2(files=(linked_dir / exact.name,)))


def test_exact_file_rejects_duplicate_path_duplicate_id_and_file_inside_root(tmp_path):
    module = load_module()
    root = tmp_path / "root"
    root.mkdir()
    exact = root / "historical.tar.gz"
    exact.write_bytes(b"x")

    payload = request_v2(files=(exact, exact))
    with pytest.raises(module.GateD4Error, match="duplicate backup file path"):
        module.validate_request(payload)

    outside = tmp_path / "outside.tar.gz"
    outside.write_bytes(b"x")
    payload = request_v2(files=(exact, outside))
    payload["files"][1]["id"] = payload["files"][0]["id"]
    with pytest.raises(module.GateD4Error, match="duplicate backup input id"):
        module.validate_request(payload)

    with pytest.raises(module.GateD4Error, match="must not be inside a designated root"):
        module.validate_request(request_v2(root, files=(exact,)))


def test_gate_d3_state_root_is_not_recounted_as_additional_backup(monkeypatch, tmp_path):
    module = load_module()
    covered = tmp_path / "covered"
    covered.mkdir()
    monkeypatch.setattr(module, "GATE_D3_STATE_ROOT", covered.resolve())
    with pytest.raises(module.GateD4Error, match="already exhaustively covered"):
        module.validate_request(request(covered))

    exact = covered / "historical.tar.gz"
    exact.write_bytes(b"x")
    with pytest.raises(module.GateD4Error, match="already exhaustively covered"):
        module.validate_request(request_v2(files=(exact,)))


def test_gate_d3_nested_absolute_path_leak_is_rejected(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    leaked = inventory()
    leaked["manifests"] = [{"path": "/secret/absolute/path"}]
    install_fake_d3(monkeypatch, module, {"backup": leaked})

    with pytest.raises(module.GateD4Error, match="absolute path"):
        module.build_discovery(request(backup))


def test_exact_file_absolute_path_leak_is_rejected(tmp_path, monkeypatch):
    module = load_module()
    exact = tmp_path / "historical.tar.gz"
    exact.write_bytes(b"x")
    leaked = archive_inventory("/secret/archive.tar.gz")
    install_fake_d3(monkeypatch, module, by_file_name={"historical.tar.gz": leaked})

    with pytest.raises(module.GateD4Error, match="exact archive path invalid"):
        module.build_discovery(request_v2(files=(exact,)))


def test_a21_exact_archive_is_not_treated_as_legacy_candidate(tmp_path, monkeypatch):
    module = load_module()
    exact = tmp_path / "a21.tar.gz"
    exact.write_bytes(b"x")
    install_fake_d3(
        monkeypatch,
        module,
        by_file_name={"a21.tar.gz": archive_inventory("a21.tar.gz", "a" * 64, is_a21=True)},
    )

    result = module.build_discovery(request_v2(files=(exact,)))

    assert result["decision"] == "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
    assert result["complete_recovery_source_count"] == 0


def test_unsafe_exact_archive_is_not_treated_as_candidate(tmp_path, monkeypatch):
    module = load_module()
    exact = tmp_path / "unsafe.tar.gz"
    exact.write_bytes(b"x")
    install_fake_d3(
        monkeypatch,
        module,
        by_file_name={"unsafe.tar.gz": archive_inventory("unsafe.tar.gz", "a" * 64, safe=False)},
    )

    result = module.build_discovery(request_v2(files=(exact,)))

    assert result["decision"] == "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
    assert result["complete_recovery_source_count"] == 0


def test_output_is_sanitized_and_all_mutation_authorities_stay_false(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "secret-absolute-backup"
    backup.mkdir()
    install_fake_d3(monkeypatch, module, {"secret-absolute-backup": inventory("c" * 64)})

    result = module.build_discovery(request(backup))
    encoded = json.dumps(result, sort_keys=True)

    assert str(backup) not in encoded
    assert result["root_reports"][0]["root_id"] == "backup-1"
    safety = result["safety"]
    assert safety["explicit_inputs_only"] is True
    assert safety["explicit_roots_only"] is True
    assert safety["exact_file_allowlist_enabled"] is False
    assert safety["strict_49_plus_41_frozen_contract_unchanged"] is True
    for key, value in safety.items():
        if key in {
            "explicit_inputs_only",
            "explicit_roots_only",
            "strict_49_plus_41_frozen_contract_unchanged",
        }:
            continue
        assert value is False


def test_deterministic_fingerprint_across_v1_request_root_order(tmp_path, monkeypatch):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    fake = {"first": inventory("d" * 64), "second": inventory()}
    install_fake_d3(monkeypatch, module, fake)

    left = request(first, second)
    right = request(second, first)
    right["roots"][0]["id"] = "backup-2"
    right["roots"][1]["id"] = "backup-1"

    first_result = module.build_discovery(left)
    second_result = module.build_discovery(right)

    assert first_result == second_result
    assert len(first_result["diagnostic_fingerprint"]) == 64


def test_deterministic_fingerprint_across_v2_mixed_input_order(tmp_path, monkeypatch):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    file_a = tmp_path / "a.tar.gz"
    file_b = tmp_path / "b.tar.gz"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")
    install_fake_d3(
        monkeypatch,
        module,
        {"first": inventory(), "second": inventory("e" * 64)},
        {
            "a.tar.gz": archive_inventory("a.tar.gz"),
            "b.tar.gz": archive_inventory("b.tar.gz", "e" * 64),
        },
    )

    left = request_v2(first, second, files=(file_a, file_b))
    right = {
        **left,
        "roots": list(reversed(left["roots"])),
        "files": list(reversed(left["files"])),
    }

    assert module.build_discovery(left) == module.build_discovery(right)


def test_write_report_is_create_only(tmp_path):
    module = load_module()
    output = tmp_path / "report.json"
    module.write_report(output, {"decision": "x"})
    with pytest.raises(module.GateD4Error, match="already exists"):
        module.write_report(output, {"decision": "x"})


def test_source_has_no_network_or_mutating_execution_surface():
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "requests",
        "urllib",
        "subprocess",
        "os.system",
        "shutil",
        ".extract(",
        "docker",
        "psql",
        "systemctl",
    ):
        assert forbidden not in source
    assert "aldi_gate_d3_recovery_inventory.py" in source
    assert "build_inventory" in source
    assert "archive_inventory" in source
    assert module.REQUEST_SCHEMA_VERSION_V2 == 2
    assert module.RESULT_SCHEMA_VERSION == 1
    assert module.EXPECTED_GATE_D3_SHA256 == "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
