from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "runner" / "aldi_gate_d4_backup_discovery_dispatch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("aldi_gate_d4_backup_discovery_dispatch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_root(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


def valid_config(module, *, commit: str, d4: Path, d3: Path, request: Path) -> dict:
    payload = {
        "schema_version": 1,
        "audit": module.AUDIT,
        "commit_sha": commit,
        "d4_file": str(d4),
        "d4_sha256": sha(d4),
        "d3_file": str(d3),
        "d3_sha256": module.EXPECTED_D3_SHA256,
        "request_file": str(request),
        "request_sha256": sha(request),
        "dispatcher_sha256": sha(SCRIPT),
    }
    payload.update({key: False for key in module.AUTHORITY_FLAGS})
    return payload


def install_runtime(monkeypatch, module, tmp_path: Path):
    commit = "a" * 40
    runtime_root = tmp_path / "runtime"
    runtime = runtime_root / commit
    runtime.mkdir(parents=True)
    os.chmod(runtime, 0o755)
    d4 = runtime / module.D4_FILENAME
    d3 = runtime / module.D3_FILENAME
    write_root(d4, "print('d4')\n", 0o444)
    # The dispatcher requires the historically reviewed D3 SHA. Unit tests avoid
    # manufacturing a preimage and monkeypatch sha_file only for this exact file.
    write_root(d3, "d3 dependency fixture\n", 0o444)
    request = tmp_path / "request.json"
    write_root(request, '{"schema_version":1}\n', 0o600)
    config = tmp_path / "config.json"

    monkeypatch.setattr(module, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(module, "REQUEST", request)
    monkeypatch.setattr(module, "CONFIG", config)

    # Hosted GitHub runners are non-root. Keep functional fixture validation
    # mode/symlink-accurate without depending on the test process UID; root
    # ownership itself is tested independently with synthetic stat metadata.
    monkeypatch.setattr(
        module,
        "regular_root_file",
        lambda path, mode=0o600: Path(path).is_file()
        and not Path(path).is_symlink()
        and stat.S_IMODE(Path(path).stat().st_mode) == mode,
    )
    monkeypatch.setattr(
        module,
        "root_runtime_file",
        lambda path: Path(path).is_file()
        and not Path(path).is_symlink()
        and stat.S_IMODE(Path(path).stat().st_mode) in {0o444, 0o555},
    )
    monkeypatch.setattr(
        module,
        "root_runtime_dir",
        lambda path: Path(path).is_dir()
        and not Path(path).is_symlink()
        and stat.S_IMODE(Path(path).stat().st_mode) in {0o555, 0o755},
    )

    real_sha = module.sha_file

    def fixture_sha(path: Path):
        if Path(path) == d3:
            return module.EXPECTED_D3_SHA256
        return real_sha(Path(path))

    monkeypatch.setattr(module, "sha_file", fixture_sha)
    payload = valid_config(module, commit=commit, d4=d4, d3=d3, request=request)
    payload["d3_sha256"] = module.EXPECTED_D3_SHA256
    write_root(config, json.dumps(payload), 0o600)
    return commit, runtime, d4, d3, request, config, payload


def result_payload(module, decision="NO_CANDIDATE_IN_DESIGNATED_ROOTS"):
    if decision == "AMBIGUOUS_PLAUSIBLE_RECOVERY_CANDIDATES":
        identities = ["1" * 64, "2" * 64]
        authoritative_complete = False
        next_step = "bind_and_resolve_distinct_historical_identities"
    elif decision == "PLAUSIBLE_RECOVERY_CANDIDATE_FOUND":
        identities = ["1" * 64]
        authoritative_complete = False
        next_step = "bind_candidate_to_independent_historical_provenance"
    elif decision == "READY_FOR_IRRECOVERABLE_DECISION":
        identities = []
        authoritative_complete = True
        next_step = "record_separate_owner_reviewed_irrecoverable_decision"
    else:
        identities = []
        authoritative_complete = False
        next_step = "authorize_additional_explicit_backup_inputs_or_mark_source_set_complete"

    source_rows = [
        {
            "input_id": "backup-1",
            "input_kind": "root",
            "kind": "archive",
            "source": f"safe-{index}.tar.gz",
            "identity_sha256": identity,
            "provenance_status": "unbound_requires_gate_d4_binding",
            "root_id": "backup-1",
        }
        for index, identity in enumerate(identities)
    ]
    payload = {
        "schema_version": 1,
        "mode": "ALDI_GATE_D4_BOUNDED_BACKUP_DISCOVERY",
        "issue_number": 631,
        "request_schema_version": 1,
        "decision": decision,
        "authoritative_source_set_complete": authoritative_complete,
        "designated_root_count": 1,
        "designated_file_count": 0,
        "designated_input_count": 1,
        "complete_recovery_source_count": len(source_rows),
        "distinct_complete_identity_count": len(identities),
        "root_reports": [{"root_id": "backup-1", "archives": [{"path": "safe/file.tar.gz"}]}],
        "file_reports": [],
        "plausible_recovery_sources": source_rows,
        "complete_identities": identities,
        "provenance_binding_complete": False,
        "historical_recovery_authorized": False,
        "irrecoverable_decision_recorded": False,
        "next_step": next_step,
        "safety": {
            "explicit_inputs_only": True,
            "explicit_roots_only": True,
            "exact_file_allowlist_enabled": False,
            "raw_page_bytes_exported": False,
            "network_acquisition_authorized": False,
            "archive_extraction_authorized": False,
            "source_or_corpus_mutation_authorized": False,
            "manifest_regeneration_authorized": False,
            "parser_execution_authorized": False,
            "candidate_creation_authorized": False,
            "review_or_publication_write_authorized": False,
            "production_database_write_authorized": False,
            "production_deployment_authorized": False,
            "scheduler_systemd_canary_authorized": False,
            "destructive_cleanup_authorized": False,
            "newer_41_plus_41_substitution_authorized": False,
            "strict_49_plus_41_frozen_contract_unchanged": True,
        },
    }
    payload["diagnostic_fingerprint"] = hashlib.sha256(module.canonical_bytes(payload)).hexdigest()
    return payload


def test_root_ownership_helpers_fail_closed_on_non_root_metadata():
    module = load_module()

    regular = SimpleNamespace(
        lstat=lambda: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1000, st_gid=1000),
        is_symlink=lambda: False,
    )
    runtime_file = SimpleNamespace(
        lstat=lambda: SimpleNamespace(st_mode=stat.S_IFREG | 0o444, st_uid=1000, st_gid=1000),
        is_symlink=lambda: False,
    )
    runtime_dir = SimpleNamespace(
        lstat=lambda: SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=1000, st_gid=1000),
        is_symlink=lambda: False,
    )

    assert module.regular_root_file(regular) is False
    assert module.root_runtime_file(runtime_file) is False
    assert module.root_runtime_dir(runtime_dir) is False


def test_config_is_exact_schema_all_authorities_false_and_fixed_paths(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, _d4, _d3, _request, config, payload = install_runtime(monkeypatch, module, tmp_path)

    loaded = module.load_config(commit)
    assert loaded == payload

    payload["unexpected"] = True
    write_root(config, json.dumps(payload), 0o600)
    with pytest.raises(module.DispatchError, match="schema mismatch"):
        module.load_config(commit)


def test_any_authority_true_fails_closed(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, _d4, _d3, _request, config, payload = install_runtime(monkeypatch, module, tmp_path)
    payload["production_deployment_authorized"] = True
    write_root(config, json.dumps(payload), 0o600)
    with pytest.raises(module.DispatchError, match="unsafe config flag"):
        module.load_config(commit)


def test_config_rejects_runtime_path_escape(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, _d4, _d3, _request, config, payload = install_runtime(monkeypatch, module, tmp_path)
    payload["d4_file"] = "/tmp/not-the-pinned-runtime.py"
    write_root(config, json.dumps(payload), 0o600)
    with pytest.raises(module.DispatchError, match="D4 path mismatch"):
        module.load_config(commit)


def test_config_and_request_require_root_owned_0600(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, _d4, _d3, request, config, _payload = install_runtime(monkeypatch, module, tmp_path)
    os.chmod(config, 0o644)
    with pytest.raises(module.DispatchError, match="config missing or unsafe"):
        module.load_config(commit)
    os.chmod(config, 0o600)
    os.chmod(request, 0o644)
    with pytest.raises(module.DispatchError, match="request missing or unsafe"):
        module.validate_request(module.load_config(commit))


def test_request_hash_is_bound(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, _d4, _d3, request, _config, _payload = install_runtime(monkeypatch, module, tmp_path)
    loaded = module.load_config(commit)
    request.write_text('{"changed":true}\n', encoding="utf-8")
    os.chmod(request, 0o600)
    with pytest.raises(module.DispatchError, match="request SHA drift"):
        module.validate_request(loaded)


def test_runtime_requires_root_owned_read_only_files_and_exact_hashes(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, d4, _d3, _request, _config, _payload = install_runtime(monkeypatch, module, tmp_path)
    loaded = module.load_config(commit)
    module.validate_runtime(loaded, commit)

    os.chmod(d4, 0o644)
    with pytest.raises(module.DispatchError, match="D4 runtime missing or unsafe"):
        module.validate_runtime(loaded, commit)


def test_runtime_rejects_d3_dependency_identity_drift(monkeypatch, tmp_path):
    module = load_module()
    commit, _runtime, _d4, d3, _request, _config, _payload = install_runtime(monkeypatch, module, tmp_path)
    loaded = module.load_config(commit)
    real_sha = hashlib.sha256(d3.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "sha_file", lambda path: real_sha if Path(path) == d3 else hashlib.sha256(Path(path).read_bytes()).hexdigest())
    with pytest.raises(module.DispatchError, match="D3 runtime SHA drift"):
        module.validate_runtime(loaded, commit)


def test_export_must_be_direct_runner_owned_0700_empty_child(monkeypatch, tmp_path):
    module = load_module()
    export_root = tmp_path / "runner-temp"
    export_root.mkdir()
    export = export_root / f"{module.EXPORT_PREFIX}123"
    export.mkdir(mode=0o700)
    monkeypatch.setattr(module, "EXPORT_ROOT", export_root)
    runner = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    assert module.validate_export_dir(export, runner) == export

    (export / "unexpected").write_text("x")
    with pytest.raises(module.DispatchError, match="start empty"):
        module.validate_export_dir(export, runner)


def test_export_rejects_wrong_parent_prefix_and_symlink(monkeypatch, tmp_path):
    module = load_module()
    export_root = tmp_path / "runner-temp"
    export_root.mkdir()
    monkeypatch.setattr(module, "EXPORT_ROOT", export_root)
    runner = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())

    wrong = export_root / "wrong-name"
    wrong.mkdir(mode=0o700)
    with pytest.raises(module.DispatchError, match="prefix"):
        module.validate_export_dir(wrong, runner)

    target = export_root / f"{module.EXPORT_PREFIX}target"
    target.mkdir(mode=0o700)
    link = export_root / f"{module.EXPORT_PREFIX}link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(module.DispatchError, match="unsafe"):
        module.validate_export_dir(link, runner)


def test_runner_docker_group_membership_is_detected(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: SimpleNamespace(pw_gid=1001))
    monkeypatch.setattr(module.grp, "getgrall", lambda: [SimpleNamespace(gr_name="docker", gr_gid=999, gr_mem=[module.RUNNER_USER])])
    assert module.runner_in_docker_group(module.RUNNER_USER) is True


def test_result_accepts_all_four_gate_d4_decisions_and_validates_fingerprint():
    module = load_module()
    for decision in module.ALLOWED_DECISIONS:
        module.validate_result(result_payload(module, decision))

    payload = result_payload(module)
    payload["decision"] = "RECOVERY_CANDIDATE_FOUND"
    with pytest.raises(module.DispatchError, match="decision mismatch"):
        module.validate_result(payload)


def test_result_rejects_absolute_or_traversing_evidence_paths():
    module = load_module()
    payload = result_payload(module)
    payload["root_reports"][0]["archives"][0]["path"] = "/secret/backup/file.tar.gz"
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint")
    payload["diagnostic_fingerprint"] = hashlib.sha256(module.canonical_bytes(fingerprint_source)).hexdigest()
    with pytest.raises(module.DispatchError, match="absolute evidence path"):
        module.validate_result(payload)

    payload = result_payload(module)
    payload["root_reports"][0]["archives"][0]["path"] = "../secret"
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint")
    payload["diagnostic_fingerprint"] = hashlib.sha256(module.canonical_bytes(fingerprint_source)).hexdigest()
    with pytest.raises(module.DispatchError, match="traversing evidence path"):
        module.validate_result(payload)


def test_result_rejects_authority_or_final_irrecoverable_drift():
    module = load_module()
    payload = result_payload(module)
    payload["irrecoverable_decision_recorded"] = True
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint")
    payload["diagnostic_fingerprint"] = hashlib.sha256(module.canonical_bytes(fingerprint_source)).hexdigest()
    with pytest.raises(module.DispatchError, match="irrecoverable decision drift"):
        module.validate_result(payload)

    payload = result_payload(module)
    payload["safety"]["production_database_write_authorized"] = True
    fingerprint_source = dict(payload)
    fingerprint_source.pop("diagnostic_fingerprint")
    payload["diagnostic_fingerprint"] = hashlib.sha256(module.canonical_bytes(fingerprint_source)).hexdigest()
    with pytest.raises(module.DispatchError, match="unsafe result flag"):
        module.validate_result(payload)


def test_audit_command_has_fixed_runuser_and_clean_environment(monkeypatch):
    module = load_module()
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.audit_user_command("/usr/bin/python3", "/fixed/tool.py", "--help")
    assert observed["argv"][:6] == ["/usr/sbin/runuser", "-u", "andris", "--", "/usr/bin/env", "-i"]
    assert observed["argv"][-3:] == ["/usr/bin/python3", "/fixed/tool.py", "--help"]
    assert "shell" not in observed["kwargs"]
    assert observed["kwargs"]["stdin"] is module.subprocess.DEVNULL
    assert observed["kwargs"]["timeout"] == 180


def test_manifest_contains_hash_binding_not_request_contents_or_absolute_roots(tmp_path):
    module = load_module()
    export = tmp_path / "export"
    export.mkdir()
    (export / "diagnostic-result.json").write_text('{"safe":true}\n')
    (export / "diagnostic-exit-code.txt").write_text("0\n")
    module.write_manifest(
        export,
        commit_sha="a" * 40,
        decision="NO_CANDIDATE_IN_DESIGNATED_ROOTS",
        fingerprint="b" * 64,
        request_sha256="c" * 64,
        d4_sha256="d" * 64,
    )
    encoded = (export / "dispatcher-evidence-manifest.json").read_text()
    assert '"request_bound":true' in encoded
    assert '"request_sha256":"' + "c" * 64 + '"' in encoded
    assert "/home/andris" not in encoded
    assert "backup root" not in encoded
    assert '"production_deployment_authorized":false' in encoded
    assert '"irrecoverable_decision_recording_authorized":false' in encoded


def test_failure_is_not_written_to_unvalidated_arbitrary_directory(monkeypatch, tmp_path):
    module = load_module()
    arbitrary = tmp_path / "arbitrary"
    arbitrary.mkdir()
    monkeypatch.setattr(module.sys, "argv", [str(SCRIPT), "not-a-sha", str(arbitrary)])
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    assert module.main() == 1
    assert list(arbitrary.iterdir()) == []


def test_validated_export_failure_is_sanitized_without_exception_text(monkeypatch, tmp_path):
    module = load_module()
    export = tmp_path / "export"
    export.mkdir()
    secret = "/secret/backup/private-root"
    monkeypatch.setattr(module.sys, "argv", [str(SCRIPT), "a" * 40, str(export)])
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1, pw_gid=1))
    monkeypatch.setattr(module, "runner_in_docker_group", lambda name: False)
    monkeypatch.setattr(module, "validate_export_dir", lambda path, runner: export)

    def fail_config(_commit):
        raise module.DispatchError(secret)

    monkeypatch.setattr(module, "load_config", fail_config)
    assert module.main() == 1
    failure = (export / "diagnostic-failure.json").read_text()
    assert secret not in failure
    assert "raw_exception_exported" in failure
    assert '"raw_request_exported":false' in failure


def test_prepare_staging_rejects_symlink_root(monkeypatch, tmp_path):
    module = load_module()
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "target"
    target.mkdir(mode=0o700)
    link = parent / "staging-link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(module, "STAGING_ROOT", link)
    monkeypatch.setattr(module.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
    with pytest.raises(module.DispatchError, match="staging root unsafe"):
        module.prepare_staging()


def test_staged_request_is_private_to_audit_user(monkeypatch, tmp_path):
    module = load_module()
    source = tmp_path / "request-source.json"
    write_root(source, '{"roots":["secret"]}\n', 0o600)
    monkeypatch.setattr(module, "REQUEST", source)
    staging = tmp_path / "staging"
    staging.mkdir()
    user = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    staged = module.stage_request(staging, user)
    assert staged.read_bytes() == source.read_bytes()
    assert staged.stat().st_mode & 0o777 == 0o600


def test_source_has_no_network_shell_database_or_host_activation_surface():
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "urllib",
        "socket.",
        "shell=True",
        "os.system",
        ".extract(",
        "psql",
        "systemctl",
        "docker compose",
    ):
        assert forbidden not in source
    assert '"/usr/sbin/runuser"' in source
    assert "REQUEST = Path(" in source
    assert "AUTHORITY_FLAGS" in source
