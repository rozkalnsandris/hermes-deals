from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools/runner/origin_path_rpi5_pull_helper.py"
DOC = ROOT / "docs/operations/origin-path-rpi5-pull-helper.md"
LEGACY_DISPATCHER = ROOT / "tools/runner/origin-path-rpi5-audit-dispatcher.sh"
LEGACY_INSTALLER = ROOT / "tools/runner/install-origin-path-rpi5-audit.sh"

spec = importlib.util.spec_from_file_location("origin_path_rpi5_pull_helper", HELPER)
assert spec and spec.loader
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)

SOURCE_SHA = "1" * 40
AS_OF = "2026-09-03"
SHA256 = "2" * 64


def valid_registration() -> dict[str, str]:
    return {
        "schema": helper.REGISTRATION_SCHEMA,
        "capability": helper.CAPABILITY,
        "registered_source_sha": SOURCE_SHA,
        "helper_sha256": SHA256,
        "probe_sha256": "3" * 64,
    }


def valid_report() -> bytes:
    probes = []
    for pair, url in helper._expected_urls(AS_OF).items():
        target, endpoint = pair
        probes.append(
            {
                "target": target,
                "endpoint": endpoint,
                "url": url,
                "ok": True,
                "status": 200,
                "elapsed_ms": 12,
                "transport_error": None,
                "headers": {"content-type": "application/json"},
                "problem": {},
            }
        )
    payload = {
        "schema_version": "1",
        "captured_at": "2026-09-03T18:00:00+00:00",
        "as_of": AS_OF,
        "classification": "healthy",
        "severity": "ok",
        "probes": probes,
    }
    return json.dumps(payload).encode()


def test_helper_is_separate_and_has_no_generic_execution_authority():
    text = HELPER.read_text(encoding="utf-8")
    assert helper.CAPABILITY == "origin-path-audit"
    assert helper.MACHINE_ID == "rpi5"
    assert helper.PUBLIC_BASE_URL == "https://deals.rozkalns.net"
    assert helper.ORIGIN_BASE_URL == "http://192.168.0.180:9128"
    assert helper.ORIGIN_HOST == "deals.rozkalns.net"
    assert "shell=True" not in text
    assert "os.system" not in text
    assert "Popen(" not in text
    assert "sudo" not in text
    assert "github-runner" not in text
    assert "artifact_dir" not in text


def test_future_broker_interface_accepts_only_source_sha_and_date():
    args = helper._parse_args([SOURCE_SHA, AS_OF])
    assert args.registered_sha == SOURCE_SHA
    assert args.as_of == AS_OF
    with pytest.raises(SystemExit):
        helper._parse_args([SOURCE_SHA, AS_OF, "/tmp/output"])
    with pytest.raises(helper.ContractError):
        helper._parse_args(["../bad", AS_OF])
    with pytest.raises(helper.ContractError):
        helper._parse_args([SOURCE_SHA, "2026-9-3"])


def test_probe_argv_and_root_environment_are_fully_source_fixed():
    argv = helper._probe_argv(AS_OF)
    assert argv[0] == "/usr/sbin/runuser"
    assert argv[1:4] == ("-u", "andris", "--")
    assert str(helper.PROBE_PATH) in argv
    assert "--public-base-url" in argv and helper.PUBLIC_BASE_URL in argv
    assert "--origin-base-url" in argv and helper.ORIGIN_BASE_URL in argv
    assert "--origin-host" in argv and helper.ORIGIN_HOST in argv
    assert "--as-of" in argv and AS_OF in argv
    assert "/tmp" not in " ".join(argv)
    assert helper.ROOT_SUBPROCESS_ENV == {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
    }


def test_registration_rejects_capability_source_provenance_and_field_widening():
    registration = valid_registration()
    assert helper._validate_registration_payload(registration, SOURCE_SHA) == registration
    for key, value in (
        ("capability", "shell"),
        ("registered_source_sha", "4" * 40),
        ("helper_sha256", "bad"),
        ("probe_sha256", "bad"),
    ):
        mutated = dict(registration)
        mutated[key] = value
        with pytest.raises(helper.ContractError):
            helper._validate_registration_payload(mutated, SOURCE_SHA)
    widened = dict(registration)
    widened["command"] = "/bin/sh"
    with pytest.raises(helper.ContractError):
        helper._validate_registration_payload(widened, SOURCE_SHA)


def test_secure_file_identity_rejects_symlink_wrong_mode_and_hash(tmp_path: Path):
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


def test_evidence_destination_is_fixed_bounded_and_preexisting_fails_closed(tmp_path: Path):
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
    destination = helper._destination_for(SOURCE_SHA, AS_OF, machine_root=machine_root)
    assert destination == machine_root / f"{SOURCE_SHA}-{AS_OF}"
    helper._require_destination_absent(destination)
    destination.mkdir()
    with pytest.raises(helper.ContractError):
        helper._require_destination_absent(destination)
    destination.rmdir()
    machine_root.chmod(0o755)
    with pytest.raises(helper.ContractError):
        helper._validate_evidence_parent(
            evidence_root=evidence_root,
            machine_root=machine_root,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )


def test_evidence_parent_rejects_symlink_and_wrong_machine_namespace(tmp_path: Path):
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


def test_sanitizer_preserves_exact_six_probe_contract_and_rejects_unsafe_output():
    report, canonical = helper._validate_and_canonicalize_report(valid_report(), AS_OF, 0)
    assert len(report["probes"]) == 6
    assert canonical.endswith(b"\n")

    payload = json.loads(valid_report())
    payload["probes"][0]["headers"]["authorization"] = "secret"
    with pytest.raises(helper.ContractError):
        helper._validate_and_canonicalize_report(json.dumps(payload).encode(), AS_OF, 0)

    payload = json.loads(valid_report())
    payload["probes"][0]["problem"]["detail"] = "secret body"
    with pytest.raises(helper.ContractError):
        helper._validate_and_canonicalize_report(json.dumps(payload).encode(), AS_OF, 0)

    payload = json.loads(valid_report())
    payload["probes"][0]["url"] = "https://attacker.invalid/"
    with pytest.raises(helper.ContractError):
        helper._validate_and_canonicalize_report(json.dumps(payload).encode(), AS_OF, 0)

    payload = json.loads(valid_report())
    payload["command"] = "id"
    with pytest.raises(helper.ContractError):
        helper._validate_and_canonicalize_report(json.dumps(payload).encode(), AS_OF, 0)

    payload = json.loads(valid_report())
    payload["probes"][0]["target"] = []
    with pytest.raises(helper.ContractError):
        helper._validate_and_canonicalize_report(json.dumps(payload).encode(), AS_OF, 0)


def test_manifest_is_sanitized_and_explicitly_read_only():
    report, canonical = helper._validate_and_canonicalize_report(valid_report(), AS_OF, 0)
    manifest = json.loads(
        helper._manifest(
            source_sha=SOURCE_SHA,
            as_of=AS_OF,
            probe_rc=0,
            report=report,
            canonical_report=canonical,
            registration=valid_registration(),
        )
    )
    assert manifest["capability"] == "origin-path-audit"
    assert manifest["machine_id"] == "rpi5"
    assert manifest["sanitization_passed"] is True
    assert manifest["protected_values_included"] is False
    assert manifest["production_apply_authorized"] is False
    assert manifest["production_database_write"] is False
    assert manifest["production_deployment"] is False
    assert manifest["restart_or_configuration_mutation"] is False


def test_source_acceptance_does_not_modify_legacy_runner_boundary():
    dispatcher = LEGACY_DISPATCHER.read_text(encoding="utf-8")
    installer = LEGACY_INSTALLER.read_text(encoding="utf-8")
    assert "/home/github-runner/_work/_temp/hermes-deals-origin-path-audit-*" in dispatcher
    assert "github-runner:github-runner" in dispatcher
    assert "github-runner ALL=(root) NOPASSWD:" in installer
    assert "hermes-deals-origin-path-audit-dispatch" in installer


def test_documented_contract_is_non_activating_and_requires_future_live_gate():
    text = DOC.read_text(encoding="utf-8")
    assert "<registered-sha> <as-of>" in text
    assert "/var/lib/hermes-deals-audits/origin-path-audit/evidence/rpi5" in text
    assert "does not authorize installation or execution" in text
    assert "does not modify sudoers," in text
    assert "runner registration" in text
    assert "explicit LIVE" in text and "authorization" in text
    assert "legacy" in text and "dispatcher, installer and workflow remain unchanged" in text
