from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools/runner/aldi-new-baseline-weekly-shadow-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/hermes-aldi-new-baseline-weekly-shadow.yml"
EXPECTED_REASON_CODES = {'BRIDGE_PATH_DRIFT', 'REQUEST_SHA256_MISMATCH', 'SANITIZED_OUTPUT_VALIDATION_FAILED', 'PRIMARY_REPOSITORY_NOT_MAIN', 'REGISTRATION_CONFIG_INVALID', 'DISPATCHER_NOT_ROOT', 'ARTIFACT_DIRECTORY_MISSING_OR_UNSAFE', 'ARTIFACT_DIRECTORY_MODE_INVALID', 'ARTIFACT_EXPORT_FAILED', 'BRIDGE_FILE_MISSING_OR_UNSAFE', 'INVALID_EXPECTED_MAIN_SHA', 'INVALID_GITHUB_RUN_ID', 'REQUEST_MEMBER_UNSAFE', 'REGISTRATION_CONFIG_FIELD_MISSING', 'REQUEST_ROOT_DRIFT', 'ARTIFACT_DIRECTORY_OUTSIDE_ALLOWLIST', 'SANITIZED_RESULT_MISSING', 'REQUEST_MEMBER_OWNERSHIP_INVALID', 'PRIMARY_MAIN_SHA_DRIFT', 'ARTIFACT_DIRECTORY_NOT_EMPTY', 'PRIMARY_REPOSITORY_MISSING_OR_UNSAFE', 'BRIDGE_HASH_DRIFT', 'REQUEST_DIRECTORY_OWNERSHIP_INVALID', 'ARTIFACT_DIRECTORY_OWNERSHIP_INVALID', 'REQUEST_JSON_MISSING_OR_UNSAFE', 'GATE_HASH_DRIFT', 'INVALID_ARGUMENT_COUNT', 'GATE_FILE_MISSING_OR_UNSAFE', 'INVALID_REQUEST_SHA256', 'PRIMARY_ORIGIN_NOT_ALLOWLISTED', 'REGISTERED_MAIN_SHA_DRIFT', 'INVALID_AUTHORIZATION_COMMENT_ID', 'REQUEST_DIRECTORY_MISSING_OR_UNSAFE', 'REQUEST_JSON_OWNERSHIP_INVALID', 'PRIMARY_REPOSITORY_DIRTY', 'REQUEST_MEMBER_MODE_INVALID', 'REQUEST_DIRECTORY_MODE_INVALID', 'BRIDGE_STARTUP_OR_ARGUMENT_FAILURE', 'BRIDGE_FAILURE_RECEIPT_WRITE_FAILED', 'BRIDGE_EXPECTED_RECEIPT_MISSING', 'BRIDGE_PROCESS_SIGNALLED', 'BRIDGE_PROCESS_NO_OUTPUT'}


def test_every_dispatcher_fail_closed_guard_has_one_bounded_reason_code():
    text = DISPATCHER.read_text(encoding="utf-8")
    observed = set(re.findall(r"fail_code\s+([A-Z0-9_]+)", text))
    observed.update(re.findall(r"bridge_reason_code=([A-Z0-9_]+)", text))
    assert observed == EXPECTED_REASON_CODES
    assert "HERMES_WEEKLY_SHADOW_REASON_CODE=%s" in text
    assert "PRE_EVIDENCE_BLOCKED_UNKNOWN" not in text


def test_workflow_whitelists_all_dispatcher_codes_and_has_one_unexpected_fallback():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for code in EXPECTED_REASON_CODES:
        assert code in workflow
    assert "UNEXPECTED_PRE_EVIDENCE_FAILURE" in workflow
    assert "PRE_EVIDENCE_BLOCKED_UNKNOWN" not in workflow
    assert "^HERMES_WEEKLY_SHADOW_REASON_CODE=[A-Z0-9_]+$" in workflow


def test_pre_evidence_failure_always_builds_minimal_sanitized_receipt_before_log_delete():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    fallback = workflow.index('evidence_class": "pre_evidence_failure"')
    delete_log = workflow.index('rm -f -- "$dispatcher_log"')
    assert fallback < delete_log
    for key in (
        '"request_sha256"', '"authorized_main_sha"', '"authorization_comment_id"',
        '"github_run_id"', '"dispatcher_rc"', '"bounded_reason_code"', '"reason_sha256"',
    ):
        assert key in workflow
    for key in (
        '"production_canary_authorized": False', '"production_deploy_authorized": False',
        '"production_database_write_authorized": False', '"review_or_publication_write_authorized": False',
        '"source_mutation_authorized": False', '"automatic_schedule": False',
        '"automatic_approval_or_publication": False', '"historical_issue_56_completion_claimed": False',
    ):
        assert key in workflow
    assert 'result_path = root / "sanitized-result.json"' in workflow
    assert 'manifest = root / "MANIFEST.sha256"' in workflow
    assert 'echo "artifact_dir=$evidence_dir"' in workflow
    assert 'marker=""' in workflow
    assert 'if [[ "$rc" != 0 && ( -n "$marker" || ! ( -f "$artifact_dir/sanitized-result.json" && -f "$artifact_dir/MANIFEST.sha256" ) ) ]]; then' in workflow
    assert '"bridge_exit_code_class"' in workflow
    assert '"bridge_diagnostic_sha256"' in workflow


def test_dispatcher_hashes_private_bridge_log_and_emits_only_safe_process_markers():
    dispatcher = DISPATCHER.read_text(encoding="utf-8")
    assert 'BRIDGE_LOG="$tmp/bridge-private.log"' in dispatcher
    assert '>"$BRIDGE_LOG" 2>&1' in dispatcher
    assert 'bridge_diagnostic_sha256="$(sha256sum "$BRIDGE_LOG"' in dispatcher
    assert 'HERMES_WEEKLY_SHADOW_BRIDGE_EXIT_CLASS=%s' in dispatcher
    assert 'HERMES_WEEKLY_SHADOW_BRIDGE_DIAGNOSTIC_SHA256=%s' in dispatcher
    assert 'rm -f -- "$BRIDGE_LOG"' in dispatcher
    assert 'fail_code BRIDGE_OUTPUT_MISSING' not in dispatcher


def test_raw_dispatcher_log_is_never_inside_uploaded_artifact_and_success_contract_is_preserved():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'dispatcher_log="$RUNNER_TEMP/$artifact_name.dispatcher.log"' in workflow
    assert 'path: ${{ steps.dispatch.outputs.artifact_dir }}' in workflow
    assert "if: always() && steps.inspect.outputs.inspection_ok == 'true'" in workflow
    assert '"WEEKLY_SHADOW_EVIDENCE_ACCEPTED"' in workflow
    assert '"READY_FOR_PRODUCTION_CANARY_PLAN"' in workflow
    assert '[[ "$DISPATCHER_RC" == 0 ]]' in workflow
    assert '[[ "$INSPECTION_OK" == true ]]' in workflow
