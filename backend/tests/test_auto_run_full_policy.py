import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / ".github" / "auto-run-full-v1.json"
ROUTING_PATH = ROOT / ".github" / "start-mode-routing.json"
AGENTS_PATH = ROOT / "AGENTS.md"
DOC_PATH = ROOT / "docs" / "AUTO_RUN_FULL_V1.md"
FAST_PATH = ROOT / "docs" / "FAST_LANE_V2_2.md"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_machine_policy_is_bound_to_hermes_deals_controller() -> None:
    policy = _json(POLICY_PATH)
    assert policy["schema_version"] == 1
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
    assert routing["schema_version"] == 2
    assert routing["repository"] == "rozkalnsandris/hermes-deals"
    assert routing["bare_continuation_result"] == "FAST-LANE v2.2"
    auto = routing["explicit_modes"]["AUTO-RUN-FULL"]
    assert auto["canonical_prefix"] == "AUTO-RUN FULL"
    assert auto["requires_repository_argument"] == "hermes-deals"
    assert auto["requires_issue_argument"] is True
    assert auto["issue_argument_pattern"] == r"^#[1-9][0-9]*$"
    assert auto["policy"] == ".github/auto-run-full-v1.json"
    assert auto["controller_issue"] == 814
    assert auto["may_be_inferred_from_context"] is False
    assert routing["examples"]["AUTO-RUN FULL hermes-deals #812"] == "AUTO-RUN-FULL"


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
    assert "controller_issue_814" in activation["fresh_reads_required"]

    continuation = policy["continuation"]
    assert continuation["routine_ci_failure_is_owner_gate"] is False
    assert continuation["review_finding_is_owner_gate"] is False
    assert continuation["ordinary_merge_conflict_is_owner_gate"] is False
    assert continuation["session_or_turn_end_is_owner_gate"] is False
    assert continuation["identical_failure_retry_ceiling"] == 3
    assert continuation["retry_requires_materially_new_hypothesis_after_repeat"] is True


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
    fast = FAST_PATH.read_text(encoding="utf-8")

    assert "AUTO-RUN FULL hermes-deals #<issue>" in agents
    assert "PAUSED_OWNER_LIVE_GATE" in agents
    assert "AUTO-RUN FULL authorizes **source + merge only**" in doc
    assert "AUTO-RUN FULL does not silently convert any of those classes into source authority" in fast
    assert "AUTO-RUN FULL hermes-deals #812" in doc
