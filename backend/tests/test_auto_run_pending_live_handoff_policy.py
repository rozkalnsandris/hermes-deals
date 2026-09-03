import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "auto-run-full-v2.json"
DOC_PATH = ROOT / "docs" / "AUTO_RUN_FULL_V2.md"


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_pending_live_handoff_releases_only_source_controller_ownership() -> None:
    policy = _policy()
    execution = policy["execution_model"]
    handoff = policy["live"]["pending_live_handoff"]

    assert execution["one_active_issue_at_a_time"] is True
    assert execution["one_active_source_orchestration_issue_at_a_time"] is True
    assert execution["pending_live_backlog_does_not_occupy_source_controller"] is True

    assert handoff["enabled"] is True
    assert handoff["receipt_schema"] == "rozkalns.auto-run-pending-live.v1"
    assert handoff["target_issue_continuation_state"] == "PAUSED_OWNER_LIVE_GATE"
    assert handoff["controller_state_after_receipt"] == "IDLE"
    assert handoff["controller_active_issue_after_release"] is None
    assert handoff["target_issue_may_remain_open"] is True
    assert handoff["source_orchestration_ownership_ends_after_receipt"] is True


def test_pending_live_receipt_preserves_gate_without_granting_authority() -> None:
    handoff = _policy()["live"]["pending_live_handoff"]

    assert handoff["pending_live_backlog_is_not_source_authority"] is True
    assert handoff["pending_live_receipt_is_not_live_authority"] is True
    assert handoff["pending_live_receipt_is_not_auto_run_full_authority"] is True
    assert handoff[
        "returning_controller_to_idle_does_not_close_consume_imply_transfer_or_supersede_live_gate"
    ] is True
    assert handoff["later_live_requires_fresh_explicit_owner_authorization"] is True
    assert handoff["later_live_must_rebind_then_current_source_and_runtime_evidence"] is True

    assert set(handoff["required_receipt_fields"]) == {
        "repository",
        "target_issue",
        "merged_main_sha",
        "canonical_pr",
        "activation_comment_id",
        "remaining_owner_gate",
        "live_authority_granted",
    }
    assert handoff["required_receipt_values"] == {"live_authority_granted": False}


def test_controller_release_fails_closed_until_source_completion_is_proven() -> None:
    handoff = _policy()["live"]["pending_live_handoff"]

    assert set(handoff["controller_release_requires"]) == {
        "frozen_source_definition_of_done_converged",
        "canonical_pr_merged",
        "post_merge_exact_main_verified",
        "relevant_exact_main_ci_verified",
        "unresolved_actionable_review_findings_zero",
        "exact_remaining_strict_live_gate_identified",
        "pending_live_receipt_persisted",
    }
    assert set(handoff["controller_release_forbidden_when"]) == {
        "source_definition_of_done_incomplete",
        "canonical_pr_not_merged",
        "post_merge_verification_incomplete",
        "required_ci_unresolved_or_failed",
        "actionable_review_findings_unresolved",
        "remaining_mutation_class_ambiguous",
        "pending_live_receipt_missing_or_invalid",
    }
    assert "live_authority_granted" not in handoff["controller_release_requires"]


def test_release_does_not_allow_auto_run_or_live_authority_inference() -> None:
    handoff = _policy()["live"]["pending_live_handoff"]

    assert handoff["new_source_activation_after_release_requires_fresh_explicit_auto_run_full_command"] is True
    assert set(handoff["authority_may_not_be_inferred_from"]) == {
        "turpini",
        "watchdog_resume",
        "event_triggered_resume",
        "controller_state",
        "historical_authorization_receipt",
        "pending_live_receipt",
        "chat_history",
    }


def test_completion_distinguishes_issue_done_from_source_controller_release() -> None:
    completion = _policy()["completion"]

    assert completion["strict_live_required_but_not_authorized_is_not_done"] is True
    assert completion["strict_live_pending_may_end_source_controller_occupancy"] is True
    assert completion["pending_live_receipt_required_before_source_controller_release"] is True
    assert completion["controller_returns_to_idle_after_pending_live_handoff"] is True
    assert completion["target_issue_may_remain_open_after_source_controller_release"] is True


def test_human_contract_explains_non_blocking_pending_live_handoff() -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")

    assert "Pending LIVE handoff and source-controller release" in doc
    assert "rozkalns.auto-run-pending-live.v1" in doc
    assert "controller #814 may become `IDLE` with `active_issue: null`" in doc
    assert "Returning the controller to `IDLE` does not close, consume, imply, transfer or supersede the LIVE gate" in doc
    assert "fresh explicit `AUTO-RUN FULL hermes-deals #<issue>` command" in doc
