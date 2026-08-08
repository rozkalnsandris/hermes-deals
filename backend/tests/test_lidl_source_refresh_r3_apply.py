from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import pwd

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

import sys
sys.path.insert(0, str(TOOLS))

import lidl_source_refresh_r3_apply as apply  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _authorization() -> dict:
    return {
        "schema_version": 1,
        "authorization_version": "lidl-source-refresh-r3-promotion-authorization-v1",
        "decision": "approve_exact_r3_promotion",
        "approved_by": "Andris Rožkalns",
        "approved_at": "2026-08-08T17:23:00+00:00",
        "authorization_comment_id": 5227260615,
        "plan_fingerprint": apply.EXPECTED_PLAN_FINGERPRINT,
        "r2_artifact_id": apply.EXPECTED_R2_ARTIFACT_ID,
        "r2_artifact_digest": apply.EXPECTED_R2_ARTIFACT_DIGEST,
        "r3_plan_artifact_id": apply.EXPECTED_R3_PLAN_ARTIFACT_ID,
        "r3_plan_artifact_digest": apply.EXPECTED_R3_PLAN_ARTIFACT_DIGEST,
        "permissions": {
            "corpus_write": True,
            "scan_promotion": True,
            "source_review_promotion": True,
            "authority_promotion": True,
            "profile_promotion": False,
            "database_write": False,
            "review_write": False,
            "auto_approve": False,
            "auto_publish": False,
            "production_deploy": False,
            "systemd_change": False,
            "automatic_retry": False,
            "gate_c_d": False,
            "b15m2_v08": False,
        },
    }


def test_r3_authorization_is_exact_and_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_json(path, _authorization())
    validated = apply._validate_authorization(path)
    assert validated["plan_fingerprint"] == apply.EXPECTED_PLAN_FINGERPRINT

    unsafe = _authorization()
    unsafe["permissions"]["profile_promotion"] = True
    _write_json(path, unsafe)
    with pytest.raises(apply.R3ApplyError, match="permissions mismatch"):
        apply._validate_authorization(path)


def test_rename_noreplace_preserves_occupied_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "value").write_text("new", encoding="utf-8")
    (target / "value").write_text("old", encoding="utf-8")

    with pytest.raises(apply.R3ApplyError, match="exclusive rename failed"):
        apply._rename_noreplace(source, target)

    assert (target / "value").read_text(encoding="utf-8") == "old"
    assert (source / "value").read_text(encoding="utf-8") == "new"


def test_exact_r3_transaction_promotes_only_scan_and_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    flyers = corpus / "flyers"
    family_name = "synthetic-rev05"
    family = flyers / family_name
    family.mkdir(parents=True, mode=0o700)
    os.chmod(family, 0o700)

    source_pdf = family / "source.pdf"
    source_json = family / "source.json"
    source_pdf.write_bytes(b"synthetic-pdf")
    source_json.write_bytes(b'{"flyer":{"pages":[{}]}}')
    os.chmod(source_pdf, 0o600)
    os.chmod(source_json, 0o600)
    pdf_sha = sha256(source_pdf.read_bytes()).hexdigest()
    raw_sha = sha256(source_json.read_bytes()).hexdigest()

    scan_name = "scan-v631-0123456789ab"
    live_input = "1" * 64
    scan_files = {
        "SHA256SUMS": b"placeholder\n",
        "summary.json": b'{"result":"synthetic"}\n',
    }
    scan_manifest = [
        {"path": name, "bytes": len(data), "sha256": sha256(data).hexdigest()}
        for name, data in sorted(scan_files.items())
    ]
    scan_sha = apply._tree_digest(scan_manifest)
    review_bytes = b'{"review":"approved"}\n'
    review_sha = sha256(review_bytes).hexdigest()

    authority_core = {
        "schema_version": 1,
        "authority_version": "lidl-source-refresh-authority-v1",
        "decision": "accept_reviewed_parser_input_refresh",
        "scope": "gate_a_authoritative_scan_only",
        "permissions": {"gate_a_refresh_acceptance": True},
    }
    authority_core_sha = apply._semantic_digest(authority_core)
    targets = {
        "scan_dir": f"flyers/{family_name}/scans/{scan_name}",
        "source_review": f"flyers/{family_name}/source-refresh/{live_input}/source-review.json",
        "authority": f"flyers/{family_name}/source-refresh/{live_input}/authority.json",
        "promotion_receipt": f"flyers/{family_name}/source-refresh/{live_input}/promotion-receipt.json",
    }
    plan = {
        "result": "R3_PLAN_READY",
        "plan_fingerprint": apply.EXPECTED_PLAN_FINGERPRINT,
        "exact_payloads": {
            "scan_tree_sha256": scan_sha,
            "source_review_sha256": review_sha,
            "authority_core_sha256": authority_core_sha,
        },
        "authority_core": authority_core,
        "prediction": {
            "expected_gate_a_state_after_valid_promotion": "WAIT_PROFILE",
            "ready_is_forbidden_without_independent_rev05_profile": True,
        },
        "targets": targets,
        "preconditions": {"all_targets_must_be_absent": list(targets.values())},
        "scan_tree_manifest": scan_manifest,
    }

    monkeypatch.setattr(apply, "EXPECTED_OWNER_LOGIN", pwd.getpwuid(os.geteuid()).pw_name)
    monkeypatch.setattr(apply, "EXPECTED_CORPUS_ROOT", corpus.resolve())
    monkeypatch.setattr(apply, "EXPECTED_FAMILY", family_name)
    monkeypatch.setattr(apply, "EXPECTED_SCAN_NAME", scan_name)
    monkeypatch.setattr(apply, "EXPECTED_LIVE_INPUT_SHA", live_input)
    monkeypatch.setattr(apply, "EXPECTED_SCAN_TREE_SHA", scan_sha)
    monkeypatch.setattr(apply, "EXPECTED_SOURCE_REVIEW_SHA", review_sha)
    monkeypatch.setattr(apply, "EXPECTED_AUTHORITY_CORE_SHA", authority_core_sha)
    monkeypatch.setattr(apply.r3, "EXPECTED_PDF_SHA256", pdf_sha)
    monkeypatch.setattr(apply.r3, "EXPECTED_FROZEN_RAW_SHA256", raw_sha)
    monkeypatch.setattr(apply, "_load_r3_plan", lambda _: plan)
    monkeypatch.setattr(apply, "_rebuild_r3_plan", lambda _: plan)
    monkeypatch.setattr(apply, "_extract_r2_payloads", lambda _: (scan_files, review_bytes))

    auth_path = tmp_path / "authorization.json"
    _write_json(auth_path, _authorization())
    dummy_r2 = tmp_path / "r2.zip"
    dummy_r3 = tmp_path / "r3.zip"
    dummy_r2.write_bytes(b"unused")
    dummy_r3.write_bytes(b"unused")

    pdf_before = source_pdf.read_bytes()
    raw_before = source_json.read_bytes()
    result = apply.apply_exact_promotion(
        corpus_root=corpus,
        r2_zip=dummy_r2,
        r3_plan_zip=dummy_r3,
        authorization_file=auth_path,
    )

    assert result["result"] == "R3_PROMOTION_PASS"
    assert result["expected_gate_a_state"] == "WAIT_PROFILE"
    assert result["writes_performed"] == {
        "scan_directory": True,
        "source_refresh_directory": True,
        "review_profile": False,
    }
    assert source_pdf.read_bytes() == pdf_before
    assert source_json.read_bytes() == raw_before
    assert not (family / "review-profile.json").exists()

    scan_target = family / "scans" / scan_name
    assert apply._tree_digest(apply._tree_manifest(scan_target)) == scan_sha
    refresh = family / "source-refresh" / live_input
    assert (refresh / "source-review.json").read_bytes() == review_bytes
    authority = json.loads((refresh / "authority.json").read_text(encoding="utf-8"))
    assert authority["promotion"]["authorization_comment_id"] == 5227260615
    assert authority["promotion"]["r2_artifact_id"] == 9021545332
    receipt = json.loads((refresh / "promotion-receipt.json").read_text(encoding="utf-8"))
    assert receipt["safety"]["profile_promotion_performed"] is False
    assert receipt["safety"]["database_write_performed"] is False

    with pytest.raises(apply.R3ApplyError, match="already occupied"):
        apply.apply_exact_promotion(
            corpus_root=corpus,
            r2_zip=dummy_r2,
            r3_plan_zip=dummy_r3,
            authorization_file=auth_path,
        )

    assert source_pdf.read_bytes() == pdf_before
    assert source_json.read_bytes() == raw_before
    assert not (family / "review-profile.json").exists()
