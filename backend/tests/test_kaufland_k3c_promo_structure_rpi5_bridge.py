from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tools/runner/kaufland_k3c_promo_structure_bridge_validator.py"
INSTALLER_PATH = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
WORKFLOW_PATH = ROOT / ".github/workflows/kaufland-k3c-promo-structure-rpi5.yml"

_spec = importlib.util.spec_from_file_location("kaufland_k3c_bridge_validator", VALIDATOR_PATH)
assert _spec is not None and _spec.loader is not None
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


def _candidate() -> dict[str, object]:
    return {
        "relation": "siblings",
        "marker_parent_to_lca_steps": 1,
        "candidate_to_lca_steps": 1,
        "lca_tag": "div",
        "lca_locator": "rawpath:/html/body/a/div",
        "lca_price_classes": [],
        "candidate_tag": "span",
        "candidate_locator": "rawpath:/html/body/a/div/span[2]",
        "candidate_fragment_sha256": "b" * 64,
        "candidate_price_classes": ["k-price-tag"],
        "candidate_generic_price_tag_class_present": True,
        "candidate_amount_count": 1,
        "candidate_xtra_class_present": False,
        "candidate_old_price_class_present": False,
    }


def _projection() -> dict[str, object]:
    candidate = _candidate()
    signature_payload = {
        "relation": candidate["relation"],
        "marker_parent_to_lca_steps": candidate["marker_parent_to_lca_steps"],
        "candidate_to_lca_steps": candidate["candidate_to_lca_steps"],
        "candidate_tag": candidate["candidate_tag"],
        "candidate_price_classes": candidate["candidate_price_classes"],
        "candidate_generic_price_tag_class_present": candidate[
            "candidate_generic_price_tag_class_present"
        ],
        "lca_tag": candidate["lca_tag"],
        "lca_price_classes": candidate["lca_price_classes"],
    }
    signature = {
        "signature_identity_sha256": validator._json_sha(signature_payload),
        "count": 1,
        **signature_payload,
    }
    marker = {
        "marker": "text:nur",
        "marker_tag": "span",
        "marker_locator": "rawpath:/html/body/a/div/span[1]",
        "marker_fragment_sha256": "a" * 64,
        "marker_price_classes": [],
        "marker_amount_count": 0,
        "owner_card_locator": "rawpath:/html/body/a",
        "owner_card_fragment_sha256": "c" * 64,
        "public_amount_candidate_count": 1,
        "public_amount_candidate_samples": [candidate],
        "candidate_samples_truncated": False,
    }
    projection: dict[str, object] = {
        "schema_version": validator.DIAGNOSTIC_SCHEMA_VERSION,
        "contract_version": validator.DIAGNOSTIC_CONTRACT_VERSION,
        "parser_backend": validator.PARSER_BACKEND,
        "diagnostic_status": "EVIDENCE_ONLY",
        "promo_role_promoted": False,
        "promo_role_policy": validator.PROMO_ROLE_POLICY,
        "nur_marker_count": 1,
        "card_local_nur_marker_count": 1,
        "orphan_nur_marker_count": 0,
        "public_amount_candidate_pair_count": 1,
        "distinct_structure_signature_count": 1,
        "structure_signature_samples": [signature],
        "structure_signatures_truncated": False,
        "marker_samples": [marker],
        "marker_samples_truncated": False,
        "orphan_marker_samples": [],
        "orphan_marker_samples_truncated": False,
    }
    projection["projection_identity_sha256"] = validator._json_sha(projection)
    return projection


def _pass_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": validator.DIAGNOSTIC_SCHEMA_VERSION,
        "contract_version": validator.DIAGNOSTIC_CONTRACT_VERSION,
        "status": "PASS",
        "evidence_only": True,
        "promo_role_promoted": False,
        "k2_verifier": {
            "action": "NO_OP",
            "bundle_key": validator.EXPECTED_BUNDLE_KEY,
            "bundle_identity_sha256": validator.EXPECTED_BUNDLE_IDENTITY,
            "artifact_count": validator.EXPECTED_ARTIFACT_COUNT,
            "family_count": validator.EXPECTED_FAMILY_COUNT,
        },
        "target_fingerprint_before": {"identity_sha256": "d" * 64},
        "target_fingerprint_after": {"identity_sha256": "d" * 64},
        "target_fingerprint_unchanged": True,
        "second_derivation_deterministic": True,
        "projection": _projection(),
        **{field: False for field in validator._SAFETY_FIELDS},
    }
    payload["result_identity_sha256"] = validator._json_sha(payload)
    return payload


def _blocked_payload() -> dict[str, object]:
    return {
        "schema_version": validator.DIAGNOSTIC_SCHEMA_VERSION,
        "contract_version": validator.DIAGNOSTIC_CONTRACT_VERSION,
        "status": "BLOCKED",
        "reason_code": "HTML_PARSER_VERSION_MISMATCH",
        "evidence_only": True,
        "promo_role_promoted": False,
        **{field: False for field in validator._SAFETY_FIELDS},
    }


def _rehash_projection(payload: dict[str, object]) -> None:
    projection = payload["projection"]
    assert isinstance(projection, dict)
    projection_without_identity = dict(projection)
    projection_without_identity.pop("projection_identity_sha256", None)
    projection["projection_identity_sha256"] = validator._json_sha(projection_without_identity)
    payload_without_identity = dict(payload)
    payload_without_identity.pop("result_identity_sha256", None)
    payload["result_identity_sha256"] = validator._json_sha(payload_without_identity)


def test_validator_accepts_exact_sanitized_pass_receipt() -> None:
    artifact, summary = validator.validate_and_sanitize(
        _pass_payload(),
        expected_sha="1" * 40,
        diagnostic_rc=0,
    )

    assert summary["bridge_execution_status"] == "PASS"
    assert summary["diagnostic_status"] == "PASS"
    assert summary["promo_role_promoted"] is False
    assert summary["production_deploy_authorized"] is False
    assert summary["host_mutation_authorized"] is False
    assert artifact["projection"]["marker_samples"][0]["marker"] == "text:nur"
    serialized = json.dumps(artifact, sort_keys=True)
    assert "target_fingerprint_before" not in serialized
    assert "target_fingerprint_after" not in serialized
    assert "product title" not in serialized
    assert "1.99" not in serialized


def test_validator_accepts_expected_semantic_block_without_promotion() -> None:
    artifact, summary = validator.validate_and_sanitize(
        _blocked_payload(),
        expected_sha="2" * 40,
        diagnostic_rc=20,
    )

    assert artifact["diagnostic_status"] == "BLOCKED"
    assert artifact["reason_code"] == "HTML_PARSER_VERSION_MISMATCH"
    assert artifact["promo_role_promoted"] is False
    assert summary["bridge_execution_status"] == "PASS"
    assert summary["diagnostic_status"] == "BLOCKED"


def test_validator_rejects_candidate_amount_value_injection() -> None:
    payload = _pass_payload()
    projection = payload["projection"]
    assert isinstance(projection, dict)
    markers = projection["marker_samples"]
    assert isinstance(markers, list)
    candidate = markers[0]["public_amount_candidate_samples"][0]
    candidate["candidate_amount"] = "1.99"
    _rehash_projection(payload)

    with pytest.raises(validator.BridgeValidationError, match="field set mismatch"):
        validator.validate_and_sanitize(
            payload,
            expected_sha="3" * 40,
            diagnostic_rc=0,
        )


def test_validator_rejects_promo_promotion_or_extra_top_level_fields() -> None:
    promoted = _pass_payload()
    promoted["promo_role_promoted"] = True
    promoted["result_identity_sha256"] = validator._json_sha(
        {key: value for key, value in promoted.items() if key != "result_identity_sha256"}
    )
    with pytest.raises(validator.BridgeValidationError, match="promo_role_promoted"):
        validator.validate_and_sanitize(promoted, expected_sha="4" * 40, diagnostic_rc=0)

    extra = _pass_payload()
    extra["raw_html"] = "<div>not allowed</div>"
    with pytest.raises(validator.BridgeValidationError, match="field set mismatch"):
        validator.validate_and_sanitize(extra, expected_sha="4" * 40, diagnostic_rc=0)


def test_validator_rejects_status_exit_code_mismatch_and_identity_drift() -> None:
    with pytest.raises(validator.BridgeValidationError, match="must exit zero"):
        validator.validate_and_sanitize(_pass_payload(), expected_sha="5" * 40, diagnostic_rc=20)

    drifted = _pass_payload()
    drifted["projection"]["projection_identity_sha256"] = "f" * 64
    drifted["result_identity_sha256"] = validator._json_sha(
        {key: value for key, value in drifted.items() if key != "result_identity_sha256"}
    )
    with pytest.raises(validator.BridgeValidationError, match="projection identity mismatch"):
        validator.validate_and_sanitize(drifted, expected_sha="5" * 40, diagnostic_rc=0)


def test_installer_is_fixed_fail_closed_and_source_read_only() -> None:
    text = INSTALLER_PATH.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(INSTALLER_PATH)], check=True)

    assert "[[ $# -eq 1 ]]" in text
    assert "EXPECTED_SHA" in text
    assert "branch --show-current" in text
    assert "status --porcelain=v1 --untracked-files=all" in text
    assert "/home/andris/hermes-deals-retained-evidence" in text
    assert "PYTHONDONTWRITEBYTECODE=1" in text
    assert "PYTHONNOUSERSITE=1" in text
    assert "app.kaufland_k3c_promo_structure_diagnostic" in text
    assert "diagnostic-stderr.private" in text
    assert 'rm -f -- "$RAW" "$STDERR_PRIVATE"' in text
    assert "promo_role_promoted" in text
    assert "PRODUCTION_DEPLOY_AUTHORIZED=false" in text
    assert "github-runner ALL=(root) NOPASSWD:" in text
    assert "/bin/bash --noprofile --norc -c" in text

    forbidden = (
        "docker ",
        "systemctl ",
        "curl ",
        "wget ",
        "git checkout",
        "git reset",
        "git switch",
        "git pull",
        "git fetch",
        "production_database_write_performed=True",
    )
    for token in forbidden:
        assert token not in text


def test_workflow_is_manual_owner_only_and_self_hosted_job_is_tokenless() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "bridge execution requires a merged pull request" in text
    assert "merged bridge commit is not reachable from current main" in text
    assert "tree_equivalent_pr_head_ci" in text
    assert "permissions: {}" in text
    assert "hermes-deals-audit" in text
    assert "/usr/local/sbin/hermes-deals-kaufland-k3c-promo-structure-dispatch" in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "Public promo promoted: **false**" in text
    assert "Production deploy: **not authorized**" in text

    forbidden = (
        "pull_request_target:",
        "issue_comment:",
        "repository_dispatch:",
        "schedule:",
        "actions/checkout@",
        "gh api --method POST",
        "labels:",
        "docker ",
    )
    for token in forbidden:
        assert token not in text
