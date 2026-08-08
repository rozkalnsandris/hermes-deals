from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import lidl_source_refresh_r3_apply as base  # noqa: E402
import lidl_source_refresh_r3_apply_v2 as retry  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _authorization(comment_id: int = 6000000001) -> dict:
    return {
        "schema_version": 1,
        "authorization_version": retry.AUTHORIZATION_VERSION,
        "decision": retry.AUTHORIZATION_DECISION,
        "approved_by": "Andris Rožkalns",
        "approved_at": "2026-08-08T19:30:00+00:00",
        "authorization_comment_id": comment_id,
        "plan_fingerprint": base.EXPECTED_PLAN_FINGERPRINT,
        "r2_artifact_id": base.EXPECTED_R2_ARTIFACT_ID,
        "r2_artifact_digest": base.EXPECTED_R2_ARTIFACT_DIGEST,
        "r3_plan_artifact_id": base.EXPECTED_R3_PLAN_ARTIFACT_ID,
        "r3_plan_artifact_digest": base.EXPECTED_R3_PLAN_ARTIFACT_DIGEST,
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


def test_retry_authorization_requires_fresh_comment_id(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    _write_json(auth, _authorization())
    validated = retry._validate_retry_authorization(auth)
    assert validated["authorization_comment_id"] == 6000000001

    _write_json(auth, _authorization(retry.RETIRED_AUTHORIZATION_COMMENT_ID))
    with pytest.raises(base.R3ApplyError, match="cannot reuse retired authorization"):
        retry._validate_retry_authorization(auth)


def test_retry_authorization_rejects_v1_decision_and_unsafe_permissions(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    payload = _authorization()
    payload["authorization_version"] = "lidl-source-refresh-r3-promotion-authorization-v1"
    payload["decision"] = "approve_exact_r3_promotion"
    _write_json(auth, payload)
    with pytest.raises(base.R3ApplyError, match="version mismatch"):
        retry._validate_retry_authorization(auth)

    payload = _authorization()
    payload["permissions"]["automatic_retry"] = True
    _write_json(auth, payload)
    with pytest.raises(base.R3ApplyError, match="permissions mismatch"):
        retry._validate_retry_authorization(auth)


def test_retry_scopes_dynamic_binding_and_restores_base_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_path = tmp_path / "auth.json"
    fresh_id = 6000000042
    _write_json(auth_path, _authorization(fresh_id))

    original_validator = base._validate_authorization
    original_comment_id = base.EXPECTED_AUTHORIZATION_COMMENT_ID
    original_apply_version = base.APPLY_VERSION

    observed: dict[str, object] = {}

    def fake_apply(**kwargs):
        validated = base._validate_authorization(kwargs["authorization_file"])
        observed["validated_id"] = validated["authorization_comment_id"]
        observed["constant_id"] = base.EXPECTED_AUTHORIZATION_COMMENT_ID
        observed["apply_version"] = base.APPLY_VERSION
        return {
            "result": "R3_PROMOTION_PASS",
            "authorization_comment_id": base.EXPECTED_AUTHORIZATION_COMMENT_ID,
            "apply_version": base.APPLY_VERSION,
        }

    monkeypatch.setattr(base, "apply_exact_promotion", fake_apply)
    result = retry.apply_exact_promotion_retry(
        corpus_root=tmp_path / "corpus",
        r2_zip=tmp_path / "r2.zip",
        r3_plan_zip=tmp_path / "r3.zip",
        authorization_file=auth_path,
    )

    assert observed == {
        "validated_id": fresh_id,
        "constant_id": fresh_id,
        "apply_version": retry.APPLY_VERSION,
    }
    assert result["authorization_comment_id"] == fresh_id
    assert result["apply_version"] == retry.APPLY_VERSION
    assert base._validate_authorization is original_validator
    assert base.EXPECTED_AUTHORIZATION_COMMENT_ID == original_comment_id
    assert base.APPLY_VERSION == original_apply_version


def test_retry_receipt_uses_dynamic_comment_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_id = 6000000099
    auth = _authorization(fresh_id)
    monkeypatch.setattr(base, "EXPECTED_AUTHORIZATION_COMMENT_ID", fresh_id)
    monkeypatch.setattr(base, "APPLY_VERSION", retry.APPLY_VERSION)
    receipt = base._build_receipt(
        plan={"targets": {}, "prediction": {}},
        auth=auth,
        authority_sha="1" * 64,
        authorization_sha="2" * 64,
    )
    assert receipt["authorization_comment_id"] == fresh_id
    assert receipt["apply_version"] == retry.APPLY_VERSION
    assert receipt["safety"]["automatic_retry_performed"] is False
    assert receipt["safety"]["profile_promotion_performed"] is False
