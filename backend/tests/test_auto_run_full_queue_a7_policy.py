from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED_SHA = "106908294d8515f74efa02d03321883db4b8ab79"
MANIFEST_PATH = ROOT / ".github/auto-run-full-queue-adoption-v1.json"
QUEUE_POLICY_PATH = ROOT / ".github/auto-run-full-queue-v1.json"
ROUTING_PATH = ROOT / ".github/start-mode-routing.json"
LEGACY_POLICY_PATH = ROOT / ".github/auto-run-full-v2.json"
CALLER_PATH = ROOT / ".github/workflows/auto-run-full-queue-adoption-guard.yml"
DOC_PATH = ROOT / "docs/AUTO_RUN_FULL_QUEUE_V1.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_queue_manifest_fails_closed_until_source_canary_is_proven() -> None:
    manifest = load_json(MANIFEST_PATH)

    assert set(manifest) == {
        "schema",
        "repository",
        "shared_contract_sha",
        "adoption_phase",
        "queue",
        "source_canary",
        "final_live",
        "boundaries",
    }
    assert manifest["schema"] == "rozkalns.auto-run-full-queue-adoption.v1"
    assert manifest["repository"] == "rozkalnsandris/hermes-deals"
    assert manifest["shared_contract_sha"] == SHARED_SHA
    assert manifest["adoption_phase"] == "SOURCE_ONLY_CANARY"

    assert manifest["queue"] == {
        "command_active": True,
        "maximum_items": 10,
        "maximum_active_items": 1,
        "batch_source_authority": True,
        "batch_merge_authority": True,
        "live_authority": False,
    }
    assert manifest["source_canary"] == {
        "status": "NOT_PROVEN",
        "queue_id": None,
        "controller_issue_number": None,
        "ordered_issue_numbers": [],
        "activation_main_sha": None,
        "final_main_sha": None,
        "authorization_receipt_sha256": None,
        "completion_receipt_sha256": None,
    }
    assert manifest["final_live"] == {
        "mode": "DISABLED",
        "double_execution_paths_allowed": False,
        "deferred_rpi5_requires_live_auth_v1": True,
    }
    assert manifest["boundaries"] == {
        "ops_workflows_executes_production": False,
        "ops_workflows_stores_production_credentials": False,
        "consumer_owns_rollout_adapter": True,
        "repository_local_stricter_rules_win": True,
    }


def test_reusable_guard_is_read_only_and_exact_sha_pinned() -> None:
    text = CALLER_PATH.read_text(encoding="utf-8")
    reference = (
        "rozkalnsandris/ops-workflows/.github/workflows/"
        "auto-run-full-queue-adoption-guard.yml@" + SHARED_SHA
    )

    assert "permissions:\n  contents: read" in text
    assert reference in text
    assert f"canonical_policy_sha: {SHARED_SHA}" in text
    assert "manifest_path: .github/auto-run-full-queue-adoption-v1.json" in text
    refs = re.findall(
        r"rozkalnsandris/ops-workflows/\.github/workflows/"
        r"auto-run-full-queue-adoption-guard\.yml@([^\s#]+)",
        text,
    )
    assert refs == [SHARED_SHA]
    assert "secrets:" not in text


def test_start_routing_separates_queue_from_single_issue_full() -> None:
    routing = load_json(ROUTING_PATH)
    modes = routing["explicit_modes"]
    legacy = modes["AUTO-RUN-FULL"]
    queue = modes["AUTO-RUN-FULL-QUEUE"]

    assert routing["default_continuation_mode"] == "FAST-LANE v2.2"
    assert routing["bare_continuation_result"] == "FAST-LANE v2.2"

    assert legacy["canonical_prefix"] == "AUTO-RUN FULL"
    assert legacy["requires_repository_argument"] == "hermes-deals"
    assert legacy["requires_exact_issue_argument_count"] == 1
    assert legacy["rejects_additional_issue_arguments"] is True
    assert legacy["controller_issue"] == 814
    assert legacy["policy"] == ".github/auto-run-full-v2.json"
    assert legacy["may_be_inferred_from_context"] is False

    assert queue["canonical_prefix"] == "AUTO-RUN FULL QUEUE"
    assert queue["requires_repository_argument"] == "hermes-deals"
    assert queue["minimum_issue_arguments"] == 1
    assert queue["maximum_issue_arguments"] == 10
    assert queue["issue_arguments_must_be_unique"] is True
    assert queue["issue_order_is_authoritative"] is True
    assert queue["policy"] == ".github/auto-run-full-queue-v1.json"
    assert queue["adoption_manifest"] == ".github/auto-run-full-queue-adoption-v1.json"
    assert queue["requires_separate_batch_controller_issue"] is True
    assert queue["legacy_controller_issue_may_be_reused"] is False
    assert queue["maximum_active_items"] == 1
    assert queue["may_be_inferred_from_context"] is False

    assert routing["mode_mutual_exclusion"] == {
        "legacy_single_issue_controller_issue": 814,
        "queue_uses_legacy_controller_issue": False,
        "queue_requires_separate_batch_controller_issue": True,
        "single_issue_full_activation_requires_no_active_queue": True,
        "queue_activation_requires_legacy_single_issue_controller_idle": True,
        "authority_never_transfers_between_modes": True,
        "conflict_result": "STOP_MODE_CONFLICT",
    }

    forbidden = set(routing["forbidden_mode_inference_sources"])
    assert "Queue migration issue existence" in forbidden
    assert "prior Queue authorization receipt" in forbidden
    assert routing["examples"]["AUTO-RUN FULL QUEUE hermes-deals #812 #813"] == "AUTO-RUN-FULL-QUEUE"


def test_queue_policy_preserves_a3_authority_and_a4_resume_guards() -> None:
    policy = load_json(QUEUE_POLICY_PATH)

    assert policy["shared_contract_sha"] == SHARED_SHA
    assert policy["migration_issue"] == 876
    assert policy["live_canary_issue"] == 879
    assert policy["adoption_phase"] == "SOURCE_ONLY_CANARY"
    assert policy["command"]["syntax"] == "AUTO-RUN FULL QUEUE hermes-deals #<issue1> ... #<issueN>"
    assert policy["command"]["minimum_items"] == 1
    assert policy["command"]["maximum_items"] == 10
    assert policy["command"]["issues_must_be_ordered_and_unique"] is True
    assert policy["command"]["may_be_inferred_from_start_or_turpini"] is False

    authority = policy["authority"]
    assert authority["requires_durable_batch_authorization_receipt"] is True
    assert authority["authorization_schema"] == "rozkalns.auto-run-full-queue-auth.v1"
    assert authority["source"] is True
    assert authority["merge"] is True
    assert authority["live"] is False
    assert authority["authority_applies_only_to_frozen_ordered_issue_set"] is True
    assert authority["only_active_item_may_consume_source_or_merge_authority"] is True

    controller = policy["controller"]
    assert controller["legacy_single_issue_controller"] == 814
    assert controller["reuse_legacy_controller_for_queue"] is False
    assert controller["separate_batch_controller_issue_required_per_activation"] is True
    assert controller["maximum_active_items"] == 1
    assert controller["queue_order_is_frozen"] is True
    assert controller["skip_or_reorder_on_failure"] is False

    activation = policy["activation"]
    assert "policy/simple-live-origin-path-audit-v1.json" in activation["fresh_reads_required"]
    assert activation["active_single_issue_full_blocks_queue_activation"] is True
    assert activation["active_queue_blocks_single_issue_full_activation"] is True
    assert activation["conflict_result"] == "STOP_MODE_CONFLICT"
    assert activation["post_receipt_main_stability_required"] is True

    merge = policy["merge"]
    assert merge["expected_head_sha_required"] is True
    assert merge["fresh_exact_head_ci_required"] is True
    assert merge["fresh_reviews_and_unresolved_threads_required"] is True
    assert merge["fresh_mergeability_required"] is True
    assert merge["exact_main_verification_required_before_queue_advance"] is True
    assert merge["force_merge"] is False
    assert merge["ruleset_bypass"] is False

    assert policy["resume"] == {
        "event_or_watchdog_is_authority": False,
        "fresh_canonical_github_refresh_decides_action": True,
        "stopped_auto_resume": False,
        "ready_auto_activation": False,
    }


def test_current_source_adds_no_live_or_runtime_execution() -> None:
    policy = load_json(QUEUE_POLICY_PATH)
    boundary = policy["execution_boundary"]

    assert boundary["repository_controller_executor_added_by_a7"] is False
    assert boundary["event_resume_automation_added_by_a7"] is False
    assert boundary["watchdog_added_by_a7"] is False
    assert boundary["production_executor_added_by_a7"] is False
    assert boundary["ops_workflows_executes_production"] is False
    assert boundary["ops_workflows_stores_production_credentials"] is False
    assert boundary["final_live_mode"] == "DISABLED"
    assert boundary["queue_authorizes_live"] is False
    assert boundary["production_deploy_authorized"] is False
    assert boundary["production_data_write_authorized"] is False
    assert boundary["runtime_or_host_mutation_authorized"] is False
    assert boundary["secrets_permissions_or_repository_settings_mutation_authorized"] is False
    assert boundary["rpi5_trust_boundary_preserved"] is True
    assert boundary["a8_source_creates_ready_envelope"] is False
    assert boundary["a8_source_creates_live_auth"] is False
    assert boundary["a8_source_enables_or_invokes_executor"] is False


def test_legacy_single_issue_full_remains_separate_and_non_live() -> None:
    legacy = load_json(LEGACY_POLICY_PATH)
    queue = load_json(QUEUE_POLICY_PATH)

    assert legacy["policy"] == "AUTO-RUN FULL v2"
    assert legacy["controller_issue"] == 814
    assert legacy["command"]["syntax"] == "AUTO-RUN FULL hermes-deals #<issue>"
    assert legacy["command"]["single_command_is_owner_source_and_merge_authorization"] is True
    assert legacy["command"]["single_command_is_live_authorization"] is False
    assert legacy["live"]["auto_run_full_command_is_live_authority"] is False

    compatibility = queue["compatibility"]
    assert compatibility["legacy_single_issue_policy"] == ".github/auto-run-full-v2.json"
    assert compatibility["legacy_single_issue_command"] == "AUTO-RUN FULL hermes-deals #<issue>"
    assert compatibility["legacy_single_issue_remains_available"] is True
    assert compatibility["queue_is_additive_and_explicit_only"] is True
    assert compatibility["authority_never_transfers_between_modes"] is True
    assert compatibility["queue_issue_876_is_not_activation_authority"] is True
    assert compatibility["a8_issue_879_is_not_live_authority"] is True
    assert compatibility["simple_live_and_auto_live_double_ownership_allowed"] is False


def test_human_contract_names_current_non_authority_boundaries() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "SOURCE_ONLY_CANARY" in text
    assert "source_canary.status=NOT_PROVEN" in text
    assert "AUTO-RUN FULL QUEUE hermes-deals #<issue1> ... #<issueN>" in text
    assert "rozkalns.auto-run-full-queue-auth.v1" in text
    assert "issue `#814`" in text
    assert "does not reinterpret, replace, migrate, or reuse issue `#814`" in text
    assert "STOP_MODE_CONFLICT" in text
    assert "`expected_head_sha`" in text
    assert "SIMPLE_LIVE_OWNER_DRIVEN" in text
    assert "Queue authority always has `live=false`" in text
    assert "LIVE <binding_sha256>" in text
    assert "final LIVE is disabled" in text
