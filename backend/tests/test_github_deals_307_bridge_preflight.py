from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-deals-307-bridge.yml"


def test_restricted_runner_never_reads_protected_production_tree_directly() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "PROD=/home/andris/hermes-deals" not in text
    assert 'git -C "$PROD"' not in text
    assert "/home/andris/hermes-deals" not in text
    assert "not_observed_from_restricted_runner" in text


def test_installed_dispatcher_gate_precedes_any_apply() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
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


def test_read_only_verify_branch_exits_before_apply_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    verify_branch = text.index("if [[ \"$OPERATION\" == 'verify-dual' ]]")
    verify = text.index('sudo --non-interactive "$DISPATCHER" verify-dual', verify_branch)
    success_exit = text.index("exit 0", verify)
    sudo_gate = text.index("testing_dispatcher_sudo_and_read_only_check")
    apply = text.index('sudo --non-interactive "$DISPATCHER" apply-dual')
    assert verify_branch < verify < success_exit < sudo_gate < apply


def test_raw_logs_are_cleaned_on_every_exit_and_never_uploaded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "trap cleanup EXIT" in text
    assert 'rm -f -- "$CHECK_LOG" "$APPLY_LOG" "$VERIFY_LOG" "$RECOVERY_LOG"' in text
    assert "actions/upload-artifact" not in text
    for forbidden in (
        'cat "$CHECK_LOG"',
        'cat "$APPLY_LOG"',
        'cat "$VERIFY_LOG"',
        "sudo bash",
        "sudo sh",
        "bash -c",
        "sh -c",
        "eval ",
    ):
        assert forbidden not in text
