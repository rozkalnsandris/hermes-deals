from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED_SHA = "106908294d8515f74efa02d03321883db4b8ab79"
RPI5_SHA = "6ca47e656edab8a06ad4d5116f9015efa1ab2e76"
MANIFEST_PATH = ROOT / ".github/auto-run-full-queue-adoption-v1.json"
QUEUE_POLICY_PATH = ROOT / ".github/auto-run-full-queue-v1.json"
OPERATION_PATH = ROOT / "policy/simple-live-origin-path-audit-v1.json"
DOC_PATH = ROOT / "docs/AUTO_RUN_FULL_QUEUE_V1.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_simple_live_is_staged_but_not_currently_selected() -> None:
    manifest = load_json(MANIFEST_PATH)
    policy = load_json(QUEUE_POLICY_PATH)

    assert manifest["shared_contract_sha"] == SHARED_SHA
    assert manifest["adoption_phase"] == "SOURCE_ONLY_CANARY"
    assert manifest["source_canary"]["status"] == "NOT_PROVEN"
    assert manifest["queue"]["batch_source_authority"] is True
    assert manifest["queue"]["batch_merge_authority"] is True
    assert manifest["queue"]["live_authority"] is False
    assert manifest["final_live"] == {
        "mode": "DISABLED",
        "double_execution_paths_allowed": False,
        "deferred_rpi5_requires_live_auth_v1": True,
    }
    assert policy["adoption_phase"] == "SOURCE_ONLY_CANARY"
    assert policy["execution_boundary"]["final_live_mode"] == "DISABLED"
    assert policy["simple_live"]["mode"] == "SIMPLE_LIVE_OWNER_DRIVEN"


def test_a8_operation_is_one_fixed_read_only_rpi5_contract() -> None:
    operation = load_json(OPERATION_PATH)

    assert operation["schema"] == "hermes-deals.simple-live-operation.v1"
    assert operation["repository"] == "rozkalnsandris/hermes-deals"
    assert operation["migration_issue"] == 879
    assert operation["shared_contract_sha"] == SHARED_SHA
    assert operation["mode"] == "SIMPLE_LIVE_OWNER_DRIVEN"
    assert operation["operation_id"] == "hermes-deals.origin-path-audit.v1"
    assert operation["target_alias"] == "hermes-deals-origin-path-audit"

    plane = operation["execution_plane"]
    assert plane == {
        "kind": "DEFERRED_RPI5_LIVE_AUTH_V1",
        "registry_repository": "rozkalnsandris/RPi5_main",
        "registry_sha": RPI5_SHA,
        "registry_path": "ops/deploy/executor-operations.json",
        "registry_operation_id": "hermes-deals.origin-path-audit.v1",
        "runtime_eligibility_must_be_fresh": True,
        "source_contract_does_not_enable_execution": True,
    }

    assert operation["mutation_budget"] == [
        {"class": "READ_ONLY_AUDIT_INVOCATION", "max_operations": 1}
    ]


def test_a8_ready_envelope_is_evidence_and_binds_exact_owner_command() -> None:
    operation = load_json(OPERATION_PATH)
    ready = operation["ready_envelope"]

    assert ready["schema"] == "rozkalns.simple-live-ready.v1"
    assert ready["classification"] == "OWNER_LIVE_REQUIRED"
    assert ready["ready_envelope_is_authority"] is False
    assert ready["operation_contract_digest_sha256_required"] is True
    assert ready["consumer_rules_digest_sha256_required"] is True
    assert ready["read_only_preflight_digest_sha256_required"] is True
    assert ready["fresh_expected_baseline_required"] is True
    assert ready["owner_command"] == "LIVE <binding_sha256>"
    assert ready["bare_live_is_valid"] is False

    queue_gate = operation["queue_gate"]
    assert queue_gate["queue_source_complete_required"] is True
    assert queue_gate["exact_final_main_required"] is True
    assert queue_gate["exact_main_ci_success_required"] is True
    assert queue_gate["queue_authorizes_live"] is False


def test_a8_preserves_live_auth_and_fail_closed_execution_semantics() -> None:
    operation = load_json(OPERATION_PATH)
    execution = operation["execution"]

    assert execution["deferred_rpi5_requires_live_auth_v1"] is True
    assert execution["simple_live_selected_for_operation_target"] is True
    assert execution["auto_live_may_own_same_operation_target"] is False
    assert execution["first_state_change_consumes_authorization"] is True
    assert execution["post_mutation_error_action"] == "PRESERVE_PUBLIC_SAFE_EVIDENCE_AND_STOP"
    assert execution["automatic_retry"] is False
    assert execution["automatic_rollback"] is False
    assert execution["automatic_cleanup"] is False
    assert execution["alternate_mutation_path"] is False

    source = operation["source_preparation"]
    assert source == {
        "ready_envelope_created": False,
        "live_auth_created": False,
        "executor_enabled": False,
        "operation_invoked": False,
        "host_or_runtime_mutated": False,
        "production_mutated": False,
    }


def test_a8_exclusions_block_privilege_and_production_expansion() -> None:
    operation = load_json(OPERATION_PATH)
    exclusions = set(operation["exclusions"])

    assert "production database writes" in exclusions
    assert "production deployment or cutover" in exclusions
    assert "restart or configuration mutation" in exclusions
    assert "parser or collector behavior changes" in exclusions
    assert "runner registration or deregistration" in exclusions
    assert "GitHub App credential or permission changes" in exclusions
    assert "arbitrary command path argv or environment authority" in exclusions
    assert "automatic retry rollback cleanup or alternate mutation path" in exclusions


def test_queue_policy_and_human_contract_keep_same_dormant_operation() -> None:
    policy = load_json(QUEUE_POLICY_PATH)
    operation = load_json(OPERATION_PATH)
    text = DOC_PATH.read_text(encoding="utf-8")

    simple = policy["simple_live"]
    assert simple["mode"] == "SIMPLE_LIVE_OWNER_DRIVEN"
    assert simple["operation_contract"] == "policy/simple-live-origin-path-audit-v1.json"
    assert simple["operation_id"] == operation["operation_id"]
    assert simple["target_alias"] == operation["target_alias"]
    assert simple["ready_envelope_schema"] == "rozkalns.simple-live-ready.v1"
    assert simple["owner_command"] == "LIVE <binding_sha256>"
    assert simple["ready_envelope_is_authority"] is False
    assert simple["queue_completion_is_live_authority"] is False
    assert simple["deferred_rpi5_requires_live_auth_v1"] is True
    assert simple["fresh_runtime_eligibility_required"] is True
    assert simple["source_ready_does_not_claim_runtime_enabled"] is True
    assert simple["auto_live_may_own_same_operation_target"] is False

    assert operation["operation_id"] in text
    assert operation["target_alias"] in text
    assert RPI5_SHA in text
    assert "dormant" in text
    assert "This operation is deliberately not the existing `deploy-main.yml`" in text
    assert "A bare `LIVE` is invalid" in text
