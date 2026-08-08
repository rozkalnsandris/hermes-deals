from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-deals-307-bridge.yml"


def jobs() -> dict:
    parsed = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed["jobs"]


def test_restricted_runner_never_reads_protected_production_tree_directly() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "PROD=/home/andris/hermes-deals" not in text
    assert 'git -C "$PROD"' not in text
    assert "/home/andris/hermes-deals" not in text
    assert "not_observed_from_restricted_runner" in text


def test_phase_c_installed_dispatcher_gate_precedes_any_apply() -> None:
    text = yaml.safe_dump(jobs()["phase-c"], sort_keys=True)
    runtime = text.index("validating_registered_runtime_sha")
    dispatcher = text.index("validating_installed_root_dispatcher")
    sudo_gate = text.index("testing_dispatcher_sudo_and_read_only_check")
    check = text.index('sudo --non-interactive "$DISPATCHER" check')
    apply = text.index('sudo --non-interactive "$DISPATCHER" apply-dual')
    post_apply_verify = text.rindex('sudo --non-interactive "$DISPATCHER" verify-dual')
    assert runtime < dispatcher < sudo_gate < check < apply < post_apply_verify
    assert "exact_dispatcher_sudo_not_authorized" in text
    assert "dispatcher_check_failed" in text
    assert "exact_operator_sudo_not_authorized" not in text


def test_phase_c_read_only_verify_branch_exits_before_apply_path() -> None:
    text = yaml.safe_dump(jobs()["phase-c"], sort_keys=True)
    verify_branch = text.index("if [[ \"$OPERATION\" == 'verify-dual' ]]")
    verify = text.index('sudo --non-interactive "$DISPATCHER" verify-dual', verify_branch)
    success_exit = text.index("exit 0", verify)
    sudo_gate = text.index("testing_dispatcher_sudo_and_read_only_check")
    apply = text.index('sudo --non-interactive "$DISPATCHER" apply-dual')
    assert verify_branch < verify < success_exit < sudo_gate < apply


def test_phase_d_read_only_verify_branch_exits_before_finalize_path() -> None:
    text = yaml.safe_dump(jobs()["phase-d"], sort_keys=True)
    runtime = text.index("validating_phase_d_runtime_sha")
    dispatcher = text.index("validating_installed_phase_d_dispatcher")
    verify_branch = text.index("if [[ \"$OPERATION\" == 'verify-loopback' ]]")
    verify = text.index('sudo --non-interactive "$DISPATCHER" verify-loopback', verify_branch)
    success_exit = text.index("exit 0", verify)
    preflight = text.index('sudo --non-interactive "$DISPATCHER" preflight')
    finalize = text.index('sudo --non-interactive "$DISPATCHER" finalize-loopback')
    assert runtime < dispatcher < verify_branch < verify < success_exit < preflight < finalize


def test_phase_d_finalize_requires_read_only_preflight_before_mutation() -> None:
    text = yaml.safe_dump(jobs()["phase-d"], sort_keys=True)
    preflight = text.index('sudo --non-interactive "$DISPATCHER" preflight')
    preflight_marker = text.index("HERMES_DEALS_307_LOOPBACK_PREFLIGHT=PASS")
    finalize = text.index('sudo --non-interactive "$DISPATCHER" finalize-loopback')
    assert preflight < preflight_marker < finalize
    assert "AUTO_ROLLBACK_TO_DUAL=PASS" in text
    assert "operator_finalize_failed_and_dual_state_was_restored" in text
    assert "rollback-dual" not in text


def test_raw_logs_are_cleaned_on_every_exit_and_never_uploaded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("trap cleanup EXIT") == 2
    assert 'rm -f -- "$CHECK_LOG" "$APPLY_LOG" "$VERIFY_LOG" "$RECOVERY_LOG"' in text
    assert 'rm -f -- "$PREFLIGHT_LOG" "$FINALIZE_LOG" "$VERIFY_LOG"' in text
    assert "actions/upload-artifact" not in text
    for forbidden in (
        'cat "$CHECK_LOG"',
        'cat "$APPLY_LOG"',
        'cat "$VERIFY_LOG"',
        'cat "$PREFLIGHT_LOG"',
        'cat "$FINALIZE_LOG"',
        "sudo bash",
        "sudo sh",
        "bash -c",
        "sh -c",
        "eval ",
    ):
        assert forbidden not in text
