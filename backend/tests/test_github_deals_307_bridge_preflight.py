from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-deals-307-bridge.yml"


def test_restricted_runner_never_reads_protected_production_tree_directly() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "PROD=/home/andris/hermes-deals" not in text
    assert 'git -C "$PROD"' not in text
    assert "not_observed_from_restricted_runner" in text
    assert "restricted audit runner intentionally cannot traverse" in text


def test_exact_read_only_operator_gate_precedes_any_apply() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    runtime = text.index("validating_registered_runtime_sha")
    path = text.index("validating_reviewed_operator_path")
    digest = text.index("validating_reviewed_operator_sha256")
    sudo_gate = text.index("testing_exact_operator_sudo_and_read_only_check")
    check = text.index('sudo --non-interactive "$OPERATOR" check')
    apply = text.index('sudo --non-interactive "$OPERATOR" apply-dual')
    verify = text.index('sudo --non-interactive "$OPERATOR" verify-dual')
    assert runtime < path < digest < sudo_gate < check < apply < verify
    assert "exact_operator_sudo_not_authorized" in text
    assert "operator_check_failed" in text


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
