from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import stat
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "lidl_source_refresh_r3_plan_tested",
    ROOT / "tools" / "lidl_source_refresh_r3_plan.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


FAMILY = "fixture-family--src-abcdef123456"
PDF_SHA = "1" * 64
FROZEN_RAW_SHA = "2" * 64
STABLE_SHA = "3" * 64
REFERENCE_INPUT_SHA = "4" * 64
LIVE_INPUT_SHA = "5" * 64
BINDING_SHA = "6" * 64
SCAN_RAW_SHA = "7" * 64
PARSER_SHA = "8" * 64
PARSER_VERSION = "fixture-v631"
SCAN_NAME = "scan-v631-888888888888"
REV04_PROFILE_SHA = "9" * 64
GATE_A_MERGE_SHA = "a" * 40
GATE_A_VALIDATOR_SHA = "b" * 64
ARTIFACT_ID = 42
RUN_ID = 99


def canonical_bytes(payload) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def regular_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 8, 12, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def patch_constants(monkeypatch) -> None:
    values = {
        "EXPECTED_ARTIFACT_ID": ARTIFACT_ID,
        "EXPECTED_R2_RUN_ID": RUN_ID,
        "EXPECTED_FAMILY": FAMILY,
        "EXPECTED_PDF_SHA256": PDF_SHA,
        "EXPECTED_FROZEN_RAW_SHA256": FROZEN_RAW_SHA,
        "EXPECTED_STABLE_SHA256": STABLE_SHA,
        "EXPECTED_REFERENCE_INPUT_SHA256": REFERENCE_INPUT_SHA,
        "EXPECTED_LIVE_INPUT_SHA256": LIVE_INPUT_SHA,
        "EXPECTED_BINDING_SHA256": BINDING_SHA,
        "EXPECTED_BINDING_COUNT": 140,
        "EXPECTED_PRODUCT_LINK_COUNT": 141,
        "EXPECTED_SCAN_NAME": SCAN_NAME,
        "EXPECTED_SCAN_RAW_SHA256": SCAN_RAW_SHA,
        "EXPECTED_PARSER_VERSION": PARSER_VERSION,
        "EXPECTED_PARSER_SHA256": PARSER_SHA,
        "EXPECTED_GATE_A_MERGE_SHA": GATE_A_MERGE_SHA,
        "EXPECTED_GATE_A_VALIDATOR_SHA256": GATE_A_VALIDATOR_SHA,
        "EXPECTED_REV04_PROFILE_SHA256": REV04_PROFILE_SHA,
    }
    for key, value in values.items():
        monkeypatch.setattr(MODULE, key, value)


def base_review() -> dict:
    return {
        "schema_version": 1,
        "decision": "approve_parser_input_refresh",
        "scope": "authoritative_staging_scan_only",
        "approved_by": "Andris Rozkalns",
        "approved_at": "2026-08-08T12:00:00Z",
        "note": "fixture approval",
        "flyer_key": FAMILY,
        "pdf_sha256": PDF_SHA,
        "reference_input": {
            "parser_input_identity_sha256": REFERENCE_INPUT_SHA,
            "product_binding_count": 140,
            "product_binding_sha256": BINDING_SHA,
        },
        "approved_live_input": {
            "parser_input_identity_sha256": LIVE_INPUT_SHA,
            "product_binding_count": 140,
            "product_binding_sha256": BINDING_SHA,
        },
        "observed_changes": {
            "binding_added": 0,
            "binding_removed": 0,
            "binding_title_changed": 0,
        },
        "permissions": {
            "staging_scan": True,
            "corpus_write": False,
            "db_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "systemd_change": False,
        },
    }


def rebuild_manifest(members: dict[str, bytes]) -> None:
    rows = [
        {"path": name, "bytes": len(data), "sha256": sha256(data).hexdigest()}
        for name, data in sorted(members.items())
        if name != "evidence/artifact-manifest.json"
    ]
    manifest = {
        "schema_version": 1,
        "r2_version": "fixture-r2",
        "result": MODULE.EXPECTED_R2_RESULT,
        "payload_tree_sha256": MODULE._digest_payload(rows),
        "files": rows,
        "raw_source_exported": False,
        "safety": dict(MODULE.EXPECTED_R2_SAFETY),
    }
    members["evidence/artifact-manifest.json"] = canonical_bytes(manifest)


def write_zip(path: Path, members: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        for name in sorted(members):
            archive.writestr(regular_info(name), members[name])
    return sha256(path.read_bytes()).hexdigest()


def build_fixture(monkeypatch, tmp_path: Path) -> tuple[Path, dict[str, bytes], str]:
    patch_constants(monkeypatch)

    scan_prefix = f"staging-scan/{SCAN_NAME}/"
    scan_summary = {
        "schema_version": 1,
        "workflow_version": "fixture-scan-v1",
        "flyer_key": FAMILY,
        "scan": SCAN_NAME,
        "parser_version": PARSER_VERSION,
        "parser_sha256": PARSER_SHA,
        "source": {"pdf_sha256": PDF_SHA, "raw_sha256": SCAN_RAW_SHA},
        "rows": 363,
        "physical_rows": 362,
        "online_only_rows": 1,
        "in_scope_rows": 218,
        "review_required_rows": 362,
        "accepted_physical_rows": 0,
    }
    scan_files: dict[str, bytes] = {
        f"{scan_prefix}summary.json": canonical_bytes(scan_summary),
    }
    for index in range(10):
        scan_files[f"{scan_prefix}payload-{index:02d}.txt"] = f"fixture-{index}\n".encode()

    provisional = dict(scan_files)
    scan_tree = MODULE._scan_tree_manifest(provisional)
    scan_tree_sha = MODULE._scan_tree_digest(scan_tree)
    monkeypatch.setattr(MODULE, "EXPECTED_SCAN_TREE_SHA256", scan_tree_sha)

    review = base_review()
    review_bytes = canonical_bytes(review)
    review_sha = sha256(review_bytes).hexdigest()
    monkeypatch.setattr(MODULE, "EXPECTED_REVIEW_SHA256", review_sha)

    r2_summary = {
        "schema_version": 1,
        "r2_version": "fixture-r2",
        "result": MODULE.EXPECTED_R2_RESULT,
        "source": {
            "parser_input_identity_sha256": LIVE_INPUT_SHA,
            "pdf_sha256": PDF_SHA,
            "product_binding_count": 140,
            "product_binding_sha256": BINDING_SHA,
            "product_link_count": 141,
            "raw_sha256": SCAN_RAW_SHA,
            "raw_sha_is_provenance_only": True,
            "stable_source_identity_sha256": STABLE_SHA,
        },
        "reference_input": {
            "parser_input_identity_sha256": REFERENCE_INPUT_SHA,
            "product_binding_count": 140,
            "product_binding_sha256": BINDING_SHA,
        },
        "approved_live_input": {
            "parser_input_identity_sha256": LIVE_INPUT_SHA,
            "product_binding_count": 140,
            "product_binding_sha256": BINDING_SHA,
        },
        "observed_changes": {
            "binding_added": 0,
            "binding_removed": 0,
            "binding_title_changed": 0,
        },
        "parser": {"version": PARSER_VERSION, "sha256": PARSER_SHA},
        "scan": {
            "name": SCAN_NAME,
            "tree_sha256": scan_tree_sha,
            "file_count": 11,
            "rows": 363,
            "physical_rows": 362,
            "online_only_rows": 1,
            "in_scope_rows": 218,
            "review_required_rows": 362,
            "accepted_physical_rows": 0,
        },
        "replay": {
            "isolated_runs": 2,
            "byte_identical": True,
            "scan_a_tree_sha256": scan_tree_sha,
            "scan_b_tree_sha256": scan_tree_sha,
        },
        "source_review": {
            "sha256": review_sha,
            "decision": "approve_parser_input_refresh",
            "scope": "authoritative_staging_scan_only",
        },
        "safety": dict(MODULE.EXPECTED_R2_SAFETY),
    }

    members: dict[str, bytes] = {
        **scan_files,
        "evidence/approved-source-review.json": review_bytes,
        "evidence/r2-summary.json": canonical_bytes(r2_summary),
        "evidence/scan-tree-manifest.json": canonical_bytes({"files": scan_tree}),
    }
    rebuild_manifest(members)
    assert len(members) == 15

    artifact = tmp_path / "artifact.zip"
    digest = write_zip(artifact, members)
    monkeypatch.setattr(MODULE, "EXPECTED_ARTIFACT_DIGEST", digest)
    return artifact, members, digest


def rewrite_fixture(monkeypatch, artifact: Path, members: dict[str, bytes]) -> str:
    rebuild_manifest(members)
    digest = write_zip(artifact, members)
    monkeypatch.setattr(MODULE, "EXPECTED_ARTIFACT_DIGEST", digest)
    return digest


def test_valid_artifact_produces_deterministic_plan(monkeypatch, tmp_path: Path) -> None:
    artifact, _, digest = build_fixture(monkeypatch, tmp_path)
    first = MODULE.build_plan(
        artifact_zip=artifact,
        artifact_id=ARTIFACT_ID,
        artifact_digest=digest,
    )
    second = MODULE.build_plan(
        artifact_zip=artifact,
        artifact_id=ARTIFACT_ID,
        artifact_digest=digest,
    )
    assert first == second
    assert first["result"] == "R3_PLAN_READY"
    assert first["plan_fingerprint"] == second["plan_fingerprint"]
    assert first["prediction"]["expected_gate_a_state_after_valid_promotion"] == "WAIT_PROFILE"
    assert first["prediction"]["ready_is_forbidden_without_independent_rev05_profile"] is True
    assert first["preconditions"]["exclusive_create_only"] is True
    assert first["preconditions"]["overwrite_immutable_source_forbidden"] is True
    assert first["authority_finalization_contract"]["fresh_owner_authorization_required"] is True
    assert all(
        value is False
        for key, value in first["safety"].items()
        if key != "plan_only"
    )
    assert first["safety"]["plan_only"] is True


def test_artifact_digest_mismatch_blocks(monkeypatch, tmp_path: Path) -> None:
    artifact, _, digest = build_fixture(monkeypatch, tmp_path)
    with pytest.raises(MODULE.R3PlanError, match="unexpected R2 artifact digest"):
        MODULE.build_plan(
            artifact_zip=artifact,
            artifact_id=ARTIFACT_ID,
            artifact_digest="0" * 64,
        )
    assert digest != "0" * 64


def test_raw_source_leak_blocks(monkeypatch, tmp_path: Path) -> None:
    artifact, members, _ = build_fixture(monkeypatch, tmp_path)
    victim = f"staging-scan/{SCAN_NAME}/payload-00.txt"
    members.pop(victim)
    members["source.json"] = b"{}\n"
    digest = rewrite_fixture(monkeypatch, artifact, members)
    with pytest.raises(MODULE.R3PlanError, match="raw source material leaked"):
        MODULE.build_plan(artifact_zip=artifact, artifact_id=ARTIFACT_ID, artifact_digest=digest)


def test_scan_tree_tamper_blocks(monkeypatch, tmp_path: Path) -> None:
    artifact, members, _ = build_fixture(monkeypatch, tmp_path)
    target = f"staging-scan/{SCAN_NAME}/payload-00.txt"
    members[target] = b"tampered\n"
    digest = rewrite_fixture(monkeypatch, artifact, members)
    with pytest.raises(MODULE.R3PlanError, match="retained scan tree SHA mismatch"):
        MODULE.build_plan(artifact_zip=artifact, artifact_id=ARTIFACT_ID, artifact_digest=digest)


def test_source_review_tamper_blocks(monkeypatch, tmp_path: Path) -> None:
    artifact, members, _ = build_fixture(monkeypatch, tmp_path)
    review = json.loads(members["evidence/approved-source-review.json"])
    review["note"] = "tampered review"
    members["evidence/approved-source-review.json"] = canonical_bytes(review)
    digest = rewrite_fixture(monkeypatch, artifact, members)
    with pytest.raises(MODULE.R3PlanError, match="source-review SHA mismatch"):
        MODULE.build_plan(artifact_zip=artifact, artifact_id=ARTIFACT_ID, artifact_digest=digest)


def test_unsafe_zip_path_blocks(monkeypatch, tmp_path: Path) -> None:
    artifact, members, _ = build_fixture(monkeypatch, tmp_path)
    victim = f"staging-scan/{SCAN_NAME}/payload-00.txt"
    data = members.pop(victim)
    members["../escape.txt"] = data
    digest = rewrite_fixture(monkeypatch, artifact, members)
    with pytest.raises(MODULE.R3PlanError, match="unsafe artifact path"):
        MODULE.build_plan(artifact_zip=artifact, artifact_id=ARTIFACT_ID, artifact_digest=digest)
