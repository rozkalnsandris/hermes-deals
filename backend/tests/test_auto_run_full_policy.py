import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "auto-run-full-v1.json"
V2_POLICY_PATH = ROOT / ".github" / "auto-run-full-v2.json"
ROUTING_PATH = ROOT / ".github" / "start-mode-routing.json"
AGENTS_PATH = ROOT / "AGENTS.md"
DOC_PATH = ROOT / "docs" / "AUTO_RUN_FULL_V1.md"
V2_DOC_PATH = ROOT / "docs" / "AUTO_RUN_FULL_V2.md"
FAST_PATH = ROOT / "docs" / "FAST_LANE_V2_2.md"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_machine_policy_is_bound_to_hermes_deals_controller() -> None:
    policy = _json(POLICY_PATH)
    assert policy["schema_version"] == 3
    assert policy["policy"] == "AUTO-RUN FULL v1"
    assert policy["repository"] == "rozkalnsandris/hermes-deals"
    assert policy["enablement_issue"] == 815
    assert policy["controller_issue"] == 814
    assert policy["execution_model"]["one_active_issue_at_a_time"] is True
    assert policy["execution_model"]["canonical_state"] == "GITHUB"


def test_command_requires_exact_explicit_issue_scoped_form() -> None:
    policy = _json(POLICY_PATH)
    command = policy["command"]
    assert command["syntax"] == "AUTO-RUN FULL hermes-deals #<issue>"
    assert command["requires_explicit_current_command"] is True
    assert command["requires_exact_repository"] is True
    assert command["requires_exact_open_issue"] is True
    assert command["may_be_inferred_from_context"] is False
    assert command["single_command_is_owner_source_and_merge_authorization"] is True
    assert command["single_command_is_live_authorization"] is False


def test_routing_exposes_auto_run_without_changing_bare_fast_lane() -> None:
    routing = _json(ROUTING_PATH)
    assert routing["schema_version"] == 3
    assert routing["repository"] == "rozkalnsandris/hermes-deals"
    assert routing["bare_continuation_result"] == "FAST-LANE v2.2"
    assert routing["lane_roles"]["FAST-LANE v2.2"] == "SAFE_DISCOVERY_AUDIT_AND_NON_FULL_CONTINUATION"
    assert routing["lane_roles"]["AUTO-RUN-FULL"] == "NORMAL_ISSUE_SCOPED_IMPLEMENTATION"
    auto = routing["explicit_modes"]["AUTO-RUN-FULL"]
    assert auto["canonical_prefix"] == "AUTO-RUN FULL"
    assert auto["requires_repository_argument"] == "hermes-deals"
    assert auto["requires_issue_argument"] is True
    assert auto["issue_argument_pattern"] == r"^#[1-9][0-9]*$"
    assert auto["policy"] == ".github/auto-run-full-v2.json"
    assert auto["controller_issue"] == 814
    assert auto["preferred_resume"] == "GITHUB_EVENT_TRIGGERED_WORK"
    assert auto["fallback_resume"] == "HOURLY_SCHEDULED_WATCHDOG"
    assert auto["preferred_merge"] == "GITHUB_AUTO_MERGE_AFTER_FINAL_EXACT_HEAD_READINESS"
    assert auto["may_be_inferred_from_context"] is False
    assert routing["examples"]["AUTO-RUN FULL hermes-deals #812"] == "AUTO-RUN-FULL"


def test_v2_policy_is_event_driven_guarded_and_source_only() -> None:
    policy = _json(V2_POLICY_PATH)
    assert policy["schema_version"] == 4
    assert policy["policy"] == "AUTO-RUN FULL v2"
    assert policy["repository"] == "rozkalnsandris/hermes-deals"
    assert policy["controller_issue"] == 814

    lane = policy["lane_role"]
    assert lane["normal_implementation_lane"] == "AUTO-RUN FULL"
    assert lane["safe_discovery_lane"] == "FAST-LANE v2.2"
    assert lane["fast_lane_may_infer_auto_run_full"] is False

    execution = policy["execution_model"]
    assert execution["primary_resume"] == "CHATGPT_WORK_GITHUB_EVENT_TRIGGERED_TASK"
    assert execution["fallback_watchdog"] == "CHATGPT_PLUS_SCHEDULED_TASK"
    assert execution["event_triggered_work_primary"] is True
    assert execution["event_triggered_work_required_for_correctness"] is False
    assert execution["scheduled_watchdog_max_frequency"] == "PT1H"
    assert execution["event_triggered_task_max_runs_per_hour"] == 30

    merge = policy["merge"]
    assert merge["preferred_merge_mechanism"] == "GITHUB_AUTO_MERGE"
    assert merge["auto_merge_enable_only_after_final_exact_head_ready"] is True
    assert merge["final_diff_scope_review_required"] is True
    assert merge["required_ci_must_pass"] is True
    assert merge["unresolved_actionable_review_findings_must_be_zero"] is True
    assert merge["changed_head_invalidates_previous_merge_readiness"] is True
    assert merge["repository_ruleset_bypass"] is False
    assert merge["force_merge"] is False

    live = policy["live"]
    assert live["auto_run_full_command_is_live_authority"] is False
    assert live["separate_explicit_owner_live_authorization_required"] is True
    assert live["state_when_definition_of_done_requires_unapproved_strict_live"] == "PAUSED_OWNER_LIVE_GATE"

    doc = V2_DOC_PATH.read_text(encoding="utf-8")
    assert "normal implementation lane" in doc
    assert "GitHub event-triggered ChatGPT Work" in doc
    assert "Guarded GitHub auto-merge" in doc
    assert "PAUSED_OWNER_LIVE_GATE" in doc


def test_deals_strict_live_classes_are_never_implicitly_authorized() -> None:
    policy = _json(POLICY_PATH)
    live = policy["live"]
    assert live["auto_run_full_command_is_live_authority"] is False
    assert live["separate_explicit_owner_live_authorization_required"] is True
    assert live["existing_repository_live_contracts_remain_authoritative"] is True
    assert live["state_when_definition_of_done_requires_unapproved_strict_live"] == "PAUSED_OWNER_LIVE_GATE"

    strict = set(policy["strict_live_never_implied"])
    required = {
        "PRODUCTION_DEPLOY",
        "PRODUCTION_DATABASE_WRITE_OR_MIGRATION",
        "REVIEW_OR_PUBLICATION_WRITE",
        "RETAINED_OR_SOURCE_EVIDENCE_MUTATION",
        "RUNTIME_REPLAY_APPLY_OR_EXECUTOR_INVOCATION",
        "LIVE_COLLECTOR_OR_SOURCE_EXECUTION_WITH_WRITE_EFFECTS",
        "SCHEDULER_SYSTEMD_HOST_OR_CONTAINER_MUTATION",
        "SECRET_CREDENTIAL_PERMISSION_OR_TRUST_BOUNDARY_CHANGE",
        "CLOUDFLARE_DNS_ACCESS_OR_INFRASTRUCTURE_MUTATION",
        "ARBITRARY_SSH_SUDO_OR_SHELL_AUTHORITY",
    }
    assert required <= strict


def test_merge_is_exact_head_green_review_clean_and_never_forced() -> None:
    merge = _json(POLICY_PATH)["merge"]
    assert merge["auto_run_full_command_is_explicit_owner_merge_authority_for_the_frozen_issue"] is True
    assert merge["fresh_exact_head_revalidation_required"] is True
    assert merge["required_ci_must_pass"] is True
    assert merge["unresolved_actionable_review_findings_must_be_zero"] is True
    assert merge["changed_head_requires_fresh_readiness_evidence"] is True
    assert merge["force_merge"] is False


def test_activation_and_continuation_fail_closed() -> None:
    policy = _json(POLICY_PATH)
    activation = policy["activation"]
    assert activation["activation_comment_schema"] == "rozkalns.auto-run-full-authorization.v1"
    assert activation["later_issue_edits_do_not_expand_authority"] is True
    assert activation["new_scope_requires_stop"] is True
    assert activation["pre_receipt_non_metadata_mutation_requires_stop"] is True
    assert "controller_issue_814" in activation["fresh_reads_required"]

    continuation = policy["continuation"]
    assert continuation["routine_ci_failure_is_owner_gate"] is False
    assert continuation["review_finding_is_owner_gate"] is False
    assert continuation["ordinary_merge_conflict_is_owner_gate"] is False
    assert continuation["session_or_turn_end_is_owner_gate"] is False
    assert continuation["identical_failure_retry_ceiling"] == 3
    assert continuation["retry_requires_materially_new_hypothesis_after_repeat"] is True


def test_activation_receipt_and_stability_barrier_precede_source_work() -> None:
    activation = _json(POLICY_PATH)["activation"]
    assert activation["preferred_write_order"] == [
        "AUTHORIZATION_RECEIPT",
        "POST_RECEIPT_MAIN_REVALIDATION",
        "CONTROLLER_ACTIVATION",
        "SOURCE_WORK",
    ]
    required_before = set(activation["authorization_receipt_required_before"])
    assert {
        "CONTROLLER_ACTIVE_POINTER_WRITE",
        "BRANCH_CREATE",
        "SOURCE_FILE_WRITE",
        "COMMIT_OR_PUSH",
        "PR_CREATE_OR_UPDATE",
        "MERGE",
        "RUNTIME_OR_LIVE_MUTATION",
    } <= required_before
    stable_before = set(activation["stable_receipt_required_before"])
    assert {
        "CONTROLLER_WORKING_POINTER_WRITE",
        "BRANCH_CREATE",
        "SOURCE_FILE_WRITE",
        "COMMIT_OR_PUSH",
        "PR_CREATE_OR_UPDATE",
        "MERGE",
        "RUNTIME_OR_LIVE_MUTATION",
    } <= stable_before
    assert activation["post_receipt_main_revalidation_required"] is True


def test_post_receipt_main_drift_uses_immutable_superseding_receipts() -> None:
    activation = _json(POLICY_PATH)["activation"]
    stability = activation["post_receipt_main_stability"]
    recovery = activation["main_drift_before_source_recovery"]

    assert stability["barrier"] == "READ_MAIN_M0__WRITE_RECEIPT_M0__READ_MAIN_M1__REQUIRE_M1_EQUALS_M0"
    assert stability["stable_when"] == "POST_WRITE_MAIN_SHA_EQUALS_RECEIPT_ACTIVATION_MAIN_SHA"
    assert stability["only_latest_stable_receipt_is_authoritative_for_source_and_merge"] is True
    assert stability["stale_receipt_never_authorizes_source_or_merge"] is True
    assert stability["main_only_drift_consumes_owner_authorization"] is False
    assert stability["main_only_drift_requires_new_owner_command"] is False

    assert recovery["allowed"] is True
    assert recovery["old_receipt_is_immutable_audit_record"] is True
    assert recovery["old_receipt_must_not_be_deleted_or_edited"] is True
    assert recovery["superseding_receipt_required"] is True
    assert set(recovery["superseding_receipt_fields"]) == {
        "supersedes_comment_id",
        "supersession_reason",
        "activation_main_sha",
    }
    assert recovery["supersession_reason"] == "MAIN_DRIFT_BEFORE_SOURCE"
    assert recovery["superseding_receipt_must_preserve_frozen_scope"] is True
    assert recovery["latest_superseding_receipt_must_pass_post_write_main_revalidation"] is True
    assert recovery["mismatch_after_prohibited_mutation_requires_stop"] is True


def test_prior_stopped_stale_receipt_can_recover_only_under_safe_predicates() -> None:
    recovery = _json(POLICY_PATH)["activation"]["main_drift_before_source_recovery"]
    assert recovery["new_explicit_command_may_supersede_prior_stopped_stale_receipt"] is True
    assert recovery["prior_stopped_receipt_recovery_requires_controller_idle_or_same_issue_paused_external"] is True
    assert recovery["prior_stopped_receipt_recovery_requires_no_source_or_live_mutation"] is True
    predicates = set(recovery["requires_fresh_revalidation"])
    assert {
        "exact_target_issue_is_still_open",
        "target_issue_scope_is_identical_to_frozen_scope",
        "repository_rules_and_policy_are_compatible_with_frozen_scope",
        "controller_points_to_no_other_issue",
        "no_branch_source_commit_pr_merge_runtime_or_live_mutation_occurred",
        "current_main_active_pr_ci_review_and_dependencies_are_freshly_re_read",
    } <= predicates


def test_repeated_activation_main_drift_pauses_without_granting_source_authority() -> None:
    stability = _json(POLICY_PATH)["activation"]["post_receipt_main_stability"]
    assert stability["max_consecutive_inline_stabilization_attempts"] == 3
    assert stability["after_attempt_limit_state"] == "PAUSED_EXTERNAL"
    assert stability["paused_controller_pointer_allowed_after_receipt"] is True
    assert stability["paused_controller_pointer_is_source_authority"] is False
    assert stability["scheduled_resume_must_establish_stable_receipt_before_source"] is True
    assert stability["scope_or_rule_drift_is_not_main_only_drift"] is True


def test_harmless_same_target_metadata_write_can_recover_before_receipt() -> None:
    activation = _json(POLICY_PATH)["activation"]
    recovery = activation["pre_receipt_metadata_recovery"]
    assert activation["classification_metadata_write_before_receipt_is_optional"] is True
    assert recovery["allowed"] is True
    assert recovery["allowed_write_class"] == "IDEMPOTENT_SAME_TARGET_ISSUE_METADATA_ONLY"
    assert recovery["example"] == "ADD_CLASSIFICATION_LABEL"
    assert recovery["does_not_consume_owner_authorization"] is True
    assert recovery["does_not_count_as_source_mutation"] is True
    assert recovery["does_not_count_as_live_mutation"] is True
    assert recovery["receipt_must_be_persisted_before_any_non_metadata_mutation"] is True
    predicates = set(recovery["requires_fresh_revalidation"])
    assert {
        "controller_is_IDLE_with_null_active_issue",
        "exact_target_issue_is_still_open",
        "target_issue_scope_has_not_widened",
        "no_branch_source_commit_pr_merge_controller_active_runtime_or_live_mutation_occurred",
        "current_main_and_repository_rules_are_freshly_re_read",
    } <= predicates


def test_required_states_and_source_only_completion_are_explicit() -> None:
    policy = _json(POLICY_PATH)
    states = set(policy["states"])
    assert {
        "IDLE",
        "ACTIVATING",
        "WORKING",
        "WAITING_CI",
        "CORRECTING",
        "PAUSED_PLATFORM_APPROVAL",
        "PAUSED_EXTERNAL",
        "PAUSED_OWNER_LIVE_GATE",
        "VERIFYING",
        "DONE",
        "STOP_SCOPE_OR_RISK",
        "STOP_ERROR",
    } <= states

    completion = policy["completion"]
    assert completion["source_only_normal_terminal_state"] == "DONE"
    assert completion["target_issue_definition_of_done_must_be_satisfied"] is True
    assert completion["controller_returns_to_idle_on_done"] is True
    assert completion["strict_live_required_but_not_authorized_is_not_done"] is True


def test_billing_never_falls_back_to_provider_api_or_paid_credits() -> None:
    billing = _json(POLICY_PATH)["billing"]
    assert billing["primary_product"] == "CHATGPT_PLUS"
    assert billing["provider_api_keys_allowed"] is False
    assert billing["automatic_paid_credits_allowed"] is False
    assert billing["codex_required"] is False
    assert billing["copilot_required"] is False


def test_human_contracts_repeat_the_critical_safety_split() -> None:
    agents = AGENTS_PATH.read_text(encoding="utf-8")
    doc = DOC_PATH.read_text(encoding="utf-8")
    v2_doc = V2_DOC_PATH.read_text(encoding="utf-8")
    fast = FAST_PATH.read_text(encoding="utf-8")

    assert "AUTO-RUN FULL hermes-deals #<issue>" in agents
    assert "PAUSED_OWNER_LIVE_GATE" in agents
    assert "post-receipt main-stability barrier" in agents
    assert "same-scope superseding receipts" in agents
    assert "AUTO-RUN FULL authorizes **source + merge only**" in doc
    assert "same-target issue metadata write" in doc
    assert "post-receipt `main` stability barrier" in doc
    assert "supersedes_comment_id" in doc
    assert "`AUTO-RUN FULL` does not silently convert any of those classes into source authority" in fast
    assert "AUTO-RUN FULL hermes-deals #812" in doc
    assert "AUTO-RUN FULL authorizes **source + merge only**" in v2_doc
    assert "GitHub event-triggered ChatGPT Work" in v2_doc
    assert "Guarded GitHub auto-merge" in v2_doc
