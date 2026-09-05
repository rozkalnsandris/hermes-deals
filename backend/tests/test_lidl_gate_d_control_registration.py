from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "lidl_gate_d_control.py"
INSTALLER = ROOT / "tools" / "runner" / "install_lidl_gate_d_control_nonrewind.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git_blob_oid(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def fixture_config(dispatcher, *, registration_sha: str = "b" * 40):
    hashes = {
        dispatcher.SERVICE_UNIT: "1" * 64,
        dispatcher.TIMER_UNIT: "2" * 64,
        dispatcher.ALERT_UNIT: "3" * 64,
    }
    config = {
        "schema_version": 1,
        "control": dispatcher.CONTROL,
        "issue_number": 24,
        "bridge_pr": 656,
        "registration_sha": registration_sha,
        "plan_fingerprint": "",
        "repo_root": dispatcher.EXPECTED_REPO_ROOT,
        "python_path": dispatcher.EXPECTED_PYTHON_PATH,
        "corpus_root": dispatcher.EXPECTED_CORPUS_ROOT,
        "evidence_root": dispatcher.EXPECTED_EVIDENCE_ROOT,
        "target": "current",
        "schedule": {
            "on_calendar": "Mon *-*-* 06:15:00 Europe/Berlin",
            "retry_delay": "30min",
            "retry_window": "6h",
            "max_attempts": 3,
            "timeout_start": "45min",
        },
        "units": {
            name: {
                "path": str(dispatcher.CONTROL_ROOT / registration_sha / name),
                "sha256": digest,
            }
            for name, digest in hashes.items()
        },
        "activation_requires_explicit_owner_authorization": True,
        "root_registration_only": True,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
    }
    config["plan_fingerprint"] = dispatcher.plan_fingerprint(config)
    return config


def test_dispatcher_accepts_only_exact_registered_semantic_plan():
    dispatcher = load(DISPATCHER, "lidl_gate_d_control")
    config = fixture_config(dispatcher)
    dispatcher.validate_config_data(config, config["plan_fingerprint"])

    changed = dict(config)
    changed["plan_fingerprint"] = "f" * 64
    with pytest.raises(dispatcher.ControlError, match="fingerprint drift"):
        dispatcher.validate_config_data(changed, changed["plan_fingerprint"])

    unsafe = dict(config)
    unsafe["deployment_authorized"] = True
    with pytest.raises(dispatcher.ControlError, match="unsafe authority"):
        dispatcher.validate_config_data(unsafe, config["plan_fingerprint"])

    wrong = dict(config)
    wrong["evidence_root"] = "/tmp/not-reviewed"
    wrong["plan_fingerprint"] = dispatcher.plan_fingerprint(wrong)
    with pytest.raises(dispatcher.ControlError, match="reviewed Gate D path"):
        dispatcher.validate_config_data(wrong, wrong["plan_fingerprint"])


def test_installer_and_dispatcher_share_exact_fingerprint_contract():
    dispatcher = load(DISPATCHER, "lidl_gate_d_control_fingerprint")
    installer = load(INSTALLER, "install_lidl_gate_d_control")
    registration_sha = "c" * 40
    unit_hashes = {
        installer.SERVICE_UNIT: "1" * 64,
        installer.TIMER_UNIT: "2" * 64,
        installer.ALERT_UNIT: "3" * 64,
    }
    payload = installer.fingerprint_payload(
        registration_sha=registration_sha,
        on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="45min",
        unit_hashes=unit_hashes,
    )
    expected = hashlib.sha256(installer.canonical_bytes(payload)).hexdigest()
    config = installer.build_config(
        registration_sha=registration_sha,
        fingerprint=expected,
        on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="45min",
        unit_hashes=unit_hashes,
        staged_root=installer.CONTROL_ROOT / registration_sha,
    )
    assert dispatcher.plan_fingerprint(config) == expected
    dispatcher.validate_config_data(config, expected)


def test_installer_binds_exact_merged_gate_d_runtime_and_dispatcher_blob():
    installer = load(INSTALLER, "install_lidl_gate_d_control_blobs")
    assert installer.EXPECTED_BRIDGE_PR == 656
    assert installer.EXPECTED_PLANNER_BLOB == "6cbb09daa3a770e80e37ba761a2f878cdd27e0c4"
    assert installer.EXPECTED_RUNTIME_BLOB == "7085fd9fe9656bdbbeb33e5c1c840cd01ffb32c2"
    assert installer.EXPECTED_DISPATCHER_BLOB == git_blob_oid(DISPATCHER)


def test_registration_is_non_activating_and_schedule_is_operator_input():
    source = INSTALLER.read_text(encoding="utf-8")
    assert 'parser.add_argument("--on-calendar", required=True)' in source
    assert 'parser.add_argument("--retry-delay", required=True)' in source
    assert 'parser.add_argument("--retry-window", required=True)' in source
    assert 'parser.add_argument("--max-attempts", type=int, required=True)' in source
    assert 'parser.add_argument("--timeout-start", required=True)' in source
    assert '"--target", "current"' in source
    assert '"/usr/bin/systemd-analyze", "calendar"' in source
    assert '"/usr/bin/systemd-analyze", "verify"' in source
    assert "systemctl" not in source
    assert "/etc/systemd/system" not in source
    assert '"systemd_change_performed": False' in source
    assert '"timer_activation_performed": False' in source
    assert '"deployment_performed": False' in source


def test_sudo_registration_is_fingerprint_specific_and_probe_hardened():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "host Sudo is older than 1.9.10" in source
    assert "^(activate|disable|rollback) {fingerprint}$" in source
    assert 'for operation in ("activate", "disable", "rollback")' in source
    assert 'wrong_plan = "0" * 64' in source
    assert '"unknown", fingerprint' in source
    assert 'fingerprint, "extra"' in source
    assert "github-runner must not belong to Docker group" in source


def test_dispatcher_has_transactional_activation_and_exact_rollback_boundary():
    source = DISPATCHER.read_text(encoding="utf-8")
    assert 'OPERATIONS = {"activate", "disable", "rollback"}' in source
    assert 'run_command(["/usr/bin/systemd-analyze", "calendar"' in source
    assert 'run_command(["/usr/bin/systemd-analyze", "verify"' in source
    assert 'run_command(["/usr/bin/systemctl", "enable", "--now", TIMER_UNIT])' in source
    assert 'run_command(["/usr/bin/systemctl", "disable", "--now", TIMER_UNIT], check=False)' in source
    assert 'require(sha_file(path) == config["units"][name]["sha256"], f"rollback unit content drift: {name}")' in source
    assert '"rollback_preserves_evidence_root": True' in source
    assert '"deployment_authorized": False' in source
    assert "shell=True" not in source
