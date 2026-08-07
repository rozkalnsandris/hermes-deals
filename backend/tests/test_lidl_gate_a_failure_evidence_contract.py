from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "lidl-weekly-gate-a-dispatcher.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "lidl-weekly-gate-a-rpi5.yml"


def test_dispatcher_fail_closed_evidence_is_bounded_and_uploadable() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    for marker in (
        "emit_synthetic_blocked",
        "synthetic_failure_evidence",
        "failure_stage",
        "failure_reason",
        "dispatcher_exit_code",
        "dispatcher_preflight",
        "stale_run_or_staging_directory",
        "runner_evidence",
        "sanitized_summary_missing_or_unsafe",
        "safety_result_missing_or_unsafe",
        "run_request_missing_or_unsafe",
        "dispatcher_sanitization",
        "sanitized_evidence_validation_failed",
        "GATE_A_STATE=BLOCKED",
        "DISPATCHER_EXIT_CODE=30",
    ):
        assert marker in text

    # Synthetic evidence must not pretend that Git invariance was proven when
    # the trusted runner stopped before producing its safety result.
    assert "PRIMARY_WORKTREE_MODIFIED=unknown" in text
    assert "PRIMARY_GIT_INDEX_UNCHANGED=unknown" in text
    assert "AUDIT_GIT_INDEX_UNCHANGED=unknown" in text

    # Write authorities remain unambiguously disabled even in the fallback.
    for marker in (
        "CORPUS_WRITE=false",
        "PRODUCTION_DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "PRODUCTION_PUBLISH=false",
        "PRODUCTION_DEPLOY=false",
        "SYSTEMD_CHANGE=false",
        "BOUNDED_RETRY=false",
    ):
        assert marker in text


def test_dispatcher_never_exports_raw_runner_log() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert '"$STAGING/runner.log" 2>&1' in text
    assert "runner.log" not in text[text.index("manifest = {") :]
    assert "controller-execution.log" not in text
    assert "source.pdf" not in text
    assert "source.json" not in text


def test_existing_workflow_can_report_synthetic_blocked_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "state not in {\"READY\", \"NO_OP\", \"WAIT\", \"BLOCKED\"}" in text
    assert 'if state == "BLOCKED" and runner_rc != 30:' in text
    assert "actions/upload-artifact@v4" in text
    assert "if-no-files-found: error" in text
    assert '[[ "$RESULT" != "BLOCKED" ]]' in text
