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


def install_fake_d3(monkeypatch, module, by_name):
    def build_inventory(root):
        return by_name[root.name]
    monkeypatch.setattr(module, "_load_d3_module", lambda: SimpleNamespace(build_inventory=build_inventory))


def test_no_candidate_is_not_irrecoverable_without_complete_source_set(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    install_fake_d3(monkeypatch, module, {"backup": inventory()})

    result = module.build_discovery(request(backup))

    assert result["decision"] == "NO_CANDIDATE_IN_DESIGNATED_ROOTS"
    assert result["irrecoverable_decision_recorded"] is False
    assert result["authoritative_source_set_complete"] is False


def test_complete_source_set_can_only_become_ready_for_separate_irrecoverable_decision(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    install_fake_d3(monkeypatch, module, {"backup": inventory()})

    result = module.build_discovery(request(backup, complete=True))

    assert result["decision"] == "READY_FOR_IRRECOVERABLE_DECISION"
    assert result["irrecoverable_decision_recorded"] is False
    assert result["historical_recovery_authorized"] is False


def test_one_identity_is_only_plausible_until_independent_provenance_binding(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    identity = "a" * 64
    install_fake_d3(monkeypatch, module, {"backup": inventory(identity)})

    result = module.build_discovery(request(backup))

    assert result["decision"] == "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND"
    assert result["complete_identities"] == [identity]
    assert result["provenance_binding_complete"] is False
    assert result["plausible_recovery_sources"][0]["provenance_status"] == "unbound_requires_gate_d4_binding"


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


def test_distinct_identities_fail_closed_as_ambiguous(tmp_path, monkeypatch):
    module = load_module()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    install_fake_d3(monkeypatch, module, {"first": inventory("a" * 64), "second": inventory("b" * 64)})

    result = module.build_discovery(request(first, second))

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


def test_request_rejects_extra_fields_and_excessive_root_count(tmp_path):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    payload = request(backup)
    payload["unexpected"] = True
    with pytest.raises(module.GateD4Error, match="fields mismatch"):
        module.validate_request(payload)

    roots = []
    for index in range(module.MAX_ROOTS + 1):
        root = tmp_path / f"root-{index}"
        root.mkdir()
        roots.append(root)
    with pytest.raises(module.GateD4Error, match="too many"):
        module.validate_request(request(*roots))


def test_request_rejects_symlink_root(tmp_path):
    module = load_module()
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(module.GateD4Error, match="unsafe"):
        module.validate_request(request(link))


def test_gate_d3_state_root_is_not_recounted_as_additional_backup(monkeypatch, tmp_path):
    module = load_module()
    covered = tmp_path / "covered"
    covered.mkdir()
    monkeypatch.setattr(module, "GATE_D3_STATE_ROOT", covered.resolve())
    with pytest.raises(module.GateD4Error, match="already exhaustively covered"):
        module.validate_request(request(covered))


def test_gate_d3_nested_absolute_path_leak_is_rejected(tmp_path, monkeypatch):
    module = load_module()
    backup = tmp_path / "backup"
    backup.mkdir()
    leaked = inventory()
    leaked["manifests"] = [{"path": "/secret/absolute/path"}]
    install_fake_d3(monkeypatch, module, {"backup": leaked})

    with pytest.raises(module.GateD4Error, match="absolute path"):
        module.build_discovery(request(backup))


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
    assert safety["explicit_roots_only"] is True
    assert safety["strict_49_plus_41_frozen_contract_unchanged"] is True
    for key, value in safety.items():
        if key in {"explicit_roots_only", "strict_49_plus_41_frozen_contract_unchanged"}:
            continue
        assert value is False


def test_deterministic_fingerprint_across_request_root_order(tmp_path, monkeypatch):
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
    assert module.EXPECTED_GATE_D3_SHA256 == "606976346177b3a6a2965c6aab536f249f2097c41e08e76f3704990fe0473cb8"
