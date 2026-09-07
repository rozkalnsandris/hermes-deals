from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/runner/netto_19_production_readonly_pull_helper.py"
DOC = ROOT / "docs/operations/netto-19-production-readonly-pull-helper.md"
LEGACY_VERIFIER = ROOT / "tools/runner/netto_19_production_readonly_verify.py"
LEGACY_INSTALLER = ROOT / "tools/runner/install-netto-19-production-readonly-verifier.sh"
LEGACY_WORKFLOW = ROOT / ".github/workflows/netto-19-production-readonly-verify.yml"

spec = importlib.util.spec_from_file_location(
    "netto_19_production_readonly_pull_helper",
    HELPER,
)
assert spec and spec.loader
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)

SOURCE_SHA = "1" * 40
SHA256 = "2" * 64
IMAGE_ID = "sha256:" + "3" * 64
PRODUCTION_SHA = "4" * 40
RUN_ID = "20260907T173100123456Z"


def valid_registration() -> dict[str, str]:
    return {
        "schema": helper.REGISTRATION_SCHEMA,
        "capability": helper.CAPABILITY,
        "registered_source_sha": SOURCE_SHA,
        "helper_sha256": SHA256,
        "verifier_sha256": "5" * 64,
    }


def probe(day: str, snapshot: str, count: int) -> dict[str, object]:
    return {
        "date": day,
        "snapshot_id": snapshot,
        "snapshot_sha256": "6" * 64,
        "daily_netto_count": count,
        "daily_ui_high_confidence_netto_count": count,
        "weekly_high_confidence_netto_count": count,
        "weekly_ui_netto_count": count,
    }


def valid_receipt() -> dict[str, object]:
    probes = [
        probe("2026-09-07", "snapshot-current", 7),
        probe("2026-08-31", "snapshot-historical", 5),
    ]
    return {
        "schema_version": 1,
        "result": "PASS",
        "registered_sha": SOURCE_SHA,
        "production_revision": PRODUCTION_SHA,
        "production_image_ref": "hermes-deals-api:production",
        "production_image_id": IMAGE_ID,
        "runtime_version": "2026.09.07",
        "runtime_phase": "production",
        "alembic_revision": "abc123",
        "required_fix_commits_present": True,
        "daily_contract": "PASS",
        "weekly_contract": "PASS",
        "daily_ui_count_contract": "PASS",
        "daily_ui_asset_mode": "inline:production-app.js",
        "weekly_ui_count_contract": "PASS",
        "review_only_policy": "PASS",
        "covered_probe_count": 2,
        "latest_covered_probe_date": "2026-09-07",
        "latest_covered_snapshot_id": "snapshot-current",
        "latest_covered_snapshot_sha256": "6" * 64,
        "latest_covered_netto_count": 7,
        "latest_daily_ui_netto_count": 7,
        "historical_covered_probe_present": True,
        "covered_probes": probes,
        "outside_window_probe_date": "2026-09-21",
        "outside_window_netto_count": 0,
        "database_payload_unchanged": True,
        "production_git_unchanged": True,
        "rollback_target": {
            "kind": "current_running_image",
            "image_ref": "hermes-deals-api:production",
            "image_id": IMAGE_ID,
            "revision": PRODUCTION_SHA,
            "command_required": False,
            "reason": "read-only verifier performs no deployment",
        },
        "production_mutated": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "scheduler_change_performed": False,
        "host_root_change_performed": False,
    }


def test_helper_is_distinct_and_exposes_no_generic_execution_authority():
    text = HELPER.read_text(encoding="utf-8")
    assert helper.CAPABILITY == "netto-19-production-readonly-verify"
    assert helper.MACHINE_ID == "rpi5"
    assert helper.VERIFIER_PATH == Path(
        "/usr/local/libexec/hermes-deals-audits/netto-19-production-readonly-v1/"
        "netto_19_production_readonly_verify.py"
    )
    assert "shell=True" not in text
    assert "os.system" not in text
    assert "Popen(" not in text
    assert "sudo" not in text
    assert "github-runner" not in text
    assert "--evidence-dir" not in text


def test_future_broker_interface_accepts_only_registered_sha():
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
        ("verifier_sha256", "bad"),
    ):
        mutated = dict(registration)
        mutated[key] = value
        with pytest.raises(helper.ContractError):
            helper._validate_registration_payload(mutated, SOURCE_SHA)

    widened = dict(registration)
    widened["command"] = "/bin/sh"
    with pytest.raises(helper.ContractError):
        helper._validate_registration_payload(widened, SOURCE_SHA)


def test_secure_file_identity_rejects_symlink_wrong_mode_owner_and_hash(tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("trusted", encoding="utf-8")
    target.chmod(0o755)
    digest = hashlib.sha256(b"trusted").hexdigest()
    helper._validate_secure_file(
        target,
        expected_mode=0o755,
        expected_sha256=digest,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )

    target.chmod(0o775)
    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            target,
            expected_mode=0o755,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )

    target.chmod(0o755)
    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            target,
            expected_mode=0o755,
            expected_uid=os.getuid() + 1,
            expected_gid=os.getgid(),
        )

    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            target,
            expected_mode=0o755,
            expected_sha256="0" * 64,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )

    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(helper.ContractError):
        helper._validate_secure_file(
            link,
            expected_mode=0o755,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_evidence_destination_is_internal_fixed_and_preexisting_fails_closed(tmp_path: Path):
    evidence_root = tmp_path / "evidence"
    machine_root = evidence_root / "rpi5"
    evidence_root.mkdir(mode=0o700)
    machine_root.mkdir(mode=0o700)
    evidence_root.chmod(0o700)
    machine_root.chmod(0o700)

    helper._validate_evidence_parent(
        evidence_root=evidence_root,
        machine_root=machine_root,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    destination = helper._destination_for(
        SOURCE_SHA,
        RUN_ID,
        machine_root=machine_root,
    )
    assert destination == machine_root / f"{SOURCE_SHA}-{RUN_ID}"
    helper._require_destination_absent(destination)
    destination.mkdir()
    with pytest.raises(helper.ContractError):
        helper._require_destination_absent(destination)


def test_evidence_parent_rejects_symlink_and_wrong_namespace(tmp_path: Path):
    evidence_root = tmp_path / "evidence"
    real_machine = tmp_path / "real"
    evidence_root.mkdir(mode=0o700)
    real_machine.mkdir(mode=0o700)
    link = evidence_root / "rpi5"
    link.symlink_to(real_machine, target_is_directory=True)
    with pytest.raises(helper.ContractError):
        helper._validate_evidence_parent(
            evidence_root=evidence_root,
            machine_root=link,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )

    alien = evidence_root / "other"
    with pytest.raises(helper.ContractError):
        helper._validate_evidence_parent(
            evidence_root=evidence_root,
            machine_root=alien,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_run_id_is_internal_canonical_and_not_caller_authority():
    assert helper._canonical_run_id(RUN_ID) == RUN_ID
    with pytest.raises(helper.ContractError):
        helper._canonical_run_id("../../tmp")
    with pytest.raises(helper.ContractError):
        helper._canonical_run_id("20260907T173100Z")


def test_receipt_sanitizer_accepts_exact_read_only_contract():
    payload = valid_receipt()
    validated = helper._validate_receipt_payload(payload, SOURCE_SHA)
    canonical = helper._canonicalize_receipt(payload, SOURCE_SHA)
    assert validated["result"] == "PASS"
    assert json.loads(canonical)["registered_sha"] == SOURCE_SHA
    assert canonical.endswith(b"\n")


@pytest.mark.parametrize("field", helper.FALSE_POSTCONDITIONS)
def test_receipt_rejects_any_mutation_postcondition(field: str):
    payload = valid_receipt()
    payload[field] = True
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)


def test_receipt_rejects_widening_identity_mismatch_and_unsafe_values():
    payload = valid_receipt()
    payload["command"] = "id"
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)

    payload = valid_receipt()
    payload["registered_sha"] = "7" * 40
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)

    payload = valid_receipt()
    payload["runtime_phase"] = "production\nsecret"
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)

    payload = valid_receipt()
    payload["rollback_target"]["command_required"] = True
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)


def test_receipt_rejects_probe_shape_count_and_latest_summary_drift():
    payload = valid_receipt()
    payload["covered_probe_count"] = 1
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)

    payload = valid_receipt()
    payload["covered_probes"][0]["unexpected"] = "x"
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)

    payload = valid_receipt()
    payload["latest_covered_netto_count"] = 8
    with pytest.raises(helper.ContractError):
        helper._validate_receipt_payload(payload, SOURCE_SHA)


def test_manifest_is_sanitized_and_explicitly_read_only():
    receipt = helper._canonicalize_receipt(valid_receipt(), SOURCE_SHA)
    manifest = json.loads(
        helper._manifest(
            source_sha=SOURCE_SHA,
            run_id=RUN_ID,
            canonical_receipt=receipt,
            registration=valid_registration(),
        )
    )
    assert manifest["capability"] == helper.CAPABILITY
    assert manifest["machine_id"] == "rpi5"
    assert manifest["sanitization_passed"] is True
    assert manifest["protected_values_included"] is False
    for field in helper.FALSE_POSTCONDITIONS:
        assert manifest[field] is False


def test_source_acceptance_does_not_broaden_legacy_runner_boundary():
    verifier = LEGACY_VERIFIER.read_text(encoding="utf-8")
    installer = LEGACY_INSTALLER.read_text(encoding="utf-8")
    workflow = LEGACY_WORKFLOW.read_text(encoding="utf-8")
    assert "/home/github-runner/_work/_temp/hermes-netto-19-production-verify-" in verifier
    assert "github-runner:github-runner" in installer
    assert "hermes-deals-netto-19-production-readonly-verify" in installer
    assert "[self-hosted, Linux, ARM64, hermes-deals-audit]" in workflow


def test_documented_contract_is_non_activating_and_requires_future_live_gate():
    text = DOC.read_text(encoding="utf-8")
    assert "<registered-sha>" in text
    assert (
        "/var/lib/hermes-deals-audits/netto-19-production-readonly-v1/evidence/rpi5"
        in text
    )
    assert "does not authorize installation or execution" in text
    assert "does not modify sudoers," in text
    assert "runner registration" in text
    assert "explicit LIVE" in text and "authorization" in text
    assert "legacy" in text and "workflow, installer and verifier remain unchanged" in text
