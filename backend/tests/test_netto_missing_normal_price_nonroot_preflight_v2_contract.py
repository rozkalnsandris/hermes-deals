from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/runner/netto_missing_normal_price_nonroot_preflight_v2.py"
DOC = ROOT / "docs/operations/netto-missing-normal-price-nonroot-preflight-v2-pull-helper.md"
LEGACY_WORKFLOW = ROOT / ".github/workflows/netto-missing-normal-price-nonroot-preflight-v2.yml"

spec = importlib.util.spec_from_file_location(
    "netto_missing_normal_price_nonroot_preflight_v2",
    HELPER,
)
assert spec and spec.loader
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)

SOURCE_SHA = "1" * 40
SHA256 = "2" * 64


def valid_registration() -> dict[str, str]:
    return {
        "schema": helper.REGISTRATION_SCHEMA,
        "capability": helper.CAPABILITY,
        "registered_source_sha": SOURCE_SHA,
        "helper_sha256": SHA256,
    }


def valid_result() -> dict[str, object]:
    return {
        "schema": helper.RESULT_SCHEMA,
        "schema_version": 2,
        "strategy": "netto_missing_normal_price_nonroot_access_preflight_v2",
        "capability": helper.CAPABILITY,
        "registered_source_sha": SOURCE_SHA,
        "runner_user": "audit-user",
        "runner_uid": 1000,
        "n9_manifest_readable": True,
        "n9_manifest_sha256_match": True,
        "corpus_root_readable": True,
        "corpus_root_executable": True,
        "blocked_at": "campaign_identity_probe_required",
        "non_root_ready": False,
        "safe_permission_metadata": {
            "home_andris_mode": "750",
            "home_andris_uid": 1000,
            "home_andris_gid": 1000,
            "n9_parent_mode": "750",
            "corpus_root_mode": "750",
        },
        "sudo_used": False,
        "file_contents_exported": False,
        "parser_executed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
    }


def test_helper_is_capability_specific_and_exposes_no_generic_execution_authority():
    text = HELPER.read_text(encoding="utf-8")
    assert helper.CAPABILITY == "netto-missing-normal-price-nonroot-preflight-v2"
    assert helper.N9_PATH == Path(
        "/home/andris/hermes-deals-audits/"
        "netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/"
        "generated/fixture-manifest.json"
    )
    assert (
        helper.N9_SHA256
        == "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
    )
    assert helper.CORPUS_ROOT == Path("/home/andris/hermes-deals-netto-corpus/flyers")
    assert "subprocess" not in text
    assert "shell=True" not in text
    assert "os.system" not in text
    assert "Popen(" not in text
    assert "/usr/bin/sudo" not in text
    assert "subprocess.run" not in text
    assert "os.exec" not in text


def test_future_rpi5_interface_accepts_only_registered_sha():
    args = helper._parse_args([SOURCE_SHA])
    assert args.registered_sha == SOURCE_SHA
    with pytest.raises(SystemExit):
        helper._parse_args([SOURCE_SHA, "/tmp/output"])
    with pytest.raises(helper.ContractError):
        helper._parse_args(["../bad"])


def test_registration_rejects_source_provenance_and_field_widening():
    registration = valid_registration()
    assert helper._validate_registration_payload(registration, SOURCE_SHA) == registration

    for key, value in (
        ("capability", "shell"),
        ("registered_source_sha", "7" * 40),
        ("helper_sha256", "bad"),
    ):
        mutated = dict(registration)
        mutated[key] = value
        with pytest.raises(helper.ContractError):
            helper._validate_registration_payload(mutated, SOURCE_SHA)

    for field in ("command", "path", "argv", "env", "output_path"):
        widened = dict(registration)
        widened[field] = "forbidden"
        with pytest.raises(helper.ContractError):
            helper._validate_registration_payload(widened, SOURCE_SHA)


def test_secure_file_rejects_symlink_wrong_mode_owner_and_hash(tmp_path: Path):
    target = tmp_path / "registration"
    target.write_text("trusted", encoding="utf-8")
    target.chmod(0o444)
    digest = hashlib.sha256(b"trusted").hexdigest()

    helper._validate_secure_file(
        target,
        expected_mode=0o444,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
        expected_sha256=digest,
    )

    target.chmod(0o644)
    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            target,
            expected_mode=0o444,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )

    target.chmod(0o444)
    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            target,
            expected_mode=0o444,
            expected_uid=os.getuid() + 1,
            expected_gid=os.getgid(),
        )

    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            target,
            expected_mode=0o444,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            expected_sha256="0" * 64,
        )

    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            link,
            expected_mode=0o444,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_nonroot_boundary_rejects_root_and_docker_group():
    helper._validate_nonroot_boundary(1000, {"users"})
    with pytest.raises(helper.ContractError):
        helper._validate_nonroot_boundary(0, {"root"})
    with pytest.raises(helper.ContractError):
        helper._validate_nonroot_boundary(1000, {"users", "docker"})


@pytest.mark.parametrize("field", helper.FALSE_POSTCONDITIONS)
def test_evidence_rejects_any_mutation_postcondition(field: str):
    payload = valid_result()
    payload[field] = True
    with pytest.raises(helper.ContractError):
        helper._validate_result_payload(payload, SOURCE_SHA)


def test_evidence_rejects_field_widening_source_drift_and_ready_true():
    payload = valid_result()
    payload["command"] = "id"
    with pytest.raises(helper.ContractError):
        helper._validate_result_payload(payload, SOURCE_SHA)

    payload = valid_result()
    payload["registered_source_sha"] = "7" * 40
    with pytest.raises(helper.ContractError):
        helper._validate_result_payload(payload, SOURCE_SHA)

    payload = valid_result()
    payload["non_root_ready"] = True
    with pytest.raises(helper.ContractError):
        helper._validate_result_payload(payload, SOURCE_SHA)


def test_canonical_evidence_is_bounded_and_sanitized():
    encoded = helper._canonical_result(valid_result(), SOURCE_SHA)
    assert len(encoded) < helper.MAX_RESULT_BYTES
    decoded = json.loads(encoded)
    assert set(decoded) == helper.RESULT_FIELDS
    assert decoded["blocked_at"] == "campaign_identity_probe_required"
    assert decoded["file_contents_exported"] is False


def test_legacy_workflow_contract_remains_unchanged():
    text = LEGACY_WORKFLOW.read_text(encoding="utf-8")
    assert "[self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "N9_PATH: /home/andris/hermes-deals-audits/" in text
    assert (
        "N9_SHA256: 2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
        in text
    )
    assert "CORPUS_ROOT: /home/andris/hermes-deals-netto-corpus/flyers" in text
    assert "campaign_identity_probe_required" in text


def test_documented_contract_is_non_activating_and_requires_future_live_gate():
    text = DOC.read_text(encoding="utf-8")
    assert "<registered-sha>" in text
    assert "stdout-only" in text
    assert "root execution is forbidden" in text
    assert "Docker-group authority is forbidden" in text
    assert "does not authorize installation or execution" in text
    assert "legacy workflow remains unchanged" in text
    assert "explicit LIVE authorization" in text
