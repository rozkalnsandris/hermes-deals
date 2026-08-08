from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_deals_307_bridge.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-deals-307-bridge.yml"
RUNTIME_SHA = "654ec9739f8cea74ee8a4ee93e25e12bf06482cc"
PHASE_D_RUNTIME_SHA = "b7a94a8a3d150db43ac051c59a304c31e901ef21"
PHASE_C_DISPATCHER = "/usr/local/sbin/hermes-deals-307-phase-c-dispatch"
PHASE_D_DISPATCHER = "/usr/local/sbin/hermes-deals-307-phase-d-dispatch"

SPEC = importlib.util.spec_from_file_location("github_deals_307_bridge_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_event(body: str = "/hermes-307 apply-dual") -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 307},
        "comment": {"id": 5223000000, "body": body},
    }


def fake_github(url: str, _token: str):
    expected = {
        (
            "https://api.github.com/repos/rozkalnsandris/hermes-deals/compare/"
            f"{RUNTIME_SHA}...main"
        ),
        (
            "https://api.github.com/repos/rozkalnsandris/hermes-deals/compare/"
            f"{PHASE_D_RUNTIME_SHA}...main"
        ),
    }
    assert url in expected
    return {"status": "ahead"}


@pytest.mark.parametrize(
    ("body", "operation"),
    [
        ("/hermes-307 apply-dual", "apply-dual"),
        ("/hermes-307 verify-dual", "verify-dual"),
        ("/hermes-307 finalize-loopback", "finalize-loopback"),
        ("/hermes-307 verify-loopback", "verify-loopback"),
    ],
)
def test_exact_commands_only(body: str, operation: str) -> None:
    assert MODULE.parse_comment(body) == operation


@pytest.mark.parametrize(
    "body",
    [
        "/hermes-307 apply-dual ",
        " /hermes-307 apply-dual",
        "/hermes-307 apply-dual\necho pwned",
        "/hermes-307 apply-dual extra=1",
        "/hermes-307 verify-dual ",
        "/hermes-307 verify-dual extra=1",
        "/hermes-307 finalize-loopback ",
        "/hermes-307 finalize-loopback extra=1",
        "/hermes-307 verify-loopback ",
        "/hermes-307 verify-loopback extra=1",
        "/hermes-307 rollback-lan",
        "/hermes-307 rollback-dual",
        "/hermes-307 apply",
        "/hermes-307 verify",
        "/hermes-307 finalize",
        "/hermes-307",
    ],
)
def test_command_parser_fails_closed(body: str) -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError, match="allowlisted command"):
        MODULE.parse_comment(body)


@pytest.mark.parametrize(
    ("body", "operation"),
    [
        ("/hermes-307 apply-dual", "apply-dual"),
        ("/hermes-307 verify-dual", "verify-dual"),
        ("/hermes-307 finalize-loopback", "finalize-loopback"),
        ("/hermes-307 verify-loopback", "verify-loopback"),
    ],
)
def test_authorizer_binds_owner_issue_and_registered_runtimes(body: str, operation: str) -> None:
    result = MODULE.authorize_event(
        valid_event(body),
        repository="rozkalnsandris/hermes-deals",
        token="test-token",
        get_json=fake_github,
    )
    assert result == {
        "operation": operation,
        "issue_number": "307",
        "comment_id": "5223000000",
        "runtime_sha": RUNTIME_SHA,
        "phase_d_runtime_sha": PHASE_D_RUNTIME_SHA,
        "trigger_actor": "rozkalnsandris",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("login", "someone-else"), ("id", 1)],
)
def test_authorizer_rejects_non_owner(field: str, value: object) -> None:
    event = valid_event()
    event["sender"][field] = value
    with pytest.raises(MODULE.BridgeAuthorizationError, match="allowlisted"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorizer_rejects_wrong_issue() -> None:
    event = valid_event()
    event["issue"]["number"] = 323
    with pytest.raises(MODULE.BridgeAuthorizationError, match="only on issue 307"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorizer_rejects_pr_comment() -> None:
    event = valid_event()
    event["issue"]["pull_request"] = {"url": "https://example.invalid/pr/1"}
    with pytest.raises(MODULE.BridgeAuthorizationError, match="only on issues"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorizer_rejects_wrong_repository() -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError, match="unexpected repository"):
        MODULE.authorize_event(
            valid_event(),
            repository="other/repo",
            token="test-token",
            get_json=fake_github,
        )


def test_authorizer_rejects_any_registered_runtime_not_reachable_from_main() -> None:
    calls = 0

    def fake(url: str, token: str):
        nonlocal calls
        fake_github(url, token)
        calls += 1
        return {"status": "ahead" if calls == 1 else "diverged"}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="not reachable"):
        MODULE.authorize_event(
            valid_event("/hermes-307 finalize-loopback"),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_output_writer_refuses_newlines(tmp_path: Path) -> None:
    values = MODULE.authorize_event(
        valid_event(),
        repository="rozkalnsandris/hermes-deals",
        token="test-token",
        get_json=fake_github,
    )
    values["operation"] = "apply-dual\nunsafe=value"
    with pytest.raises(MODULE.BridgeAuthorizationError, match="unsafe newline"):
        MODULE.write_github_outputs(tmp_path / "out", values)


def workflow() -> dict:
    parsed = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def test_workflow_has_narrow_issue_comment_and_runner_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = workflow()
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]

    assert "workflow_dispatch:" not in text
    assert "push:" not in text
    assert "pull_request:" not in text
    assert text.count("github.event.comment.body") == 1
    assert "python tools/github_deals_307_bridge.py" in text
    assert "hermes-deals-307-transition" in text
    assert "- self-hosted" in text
    assert "- ARM64" in text
    assert "- hermes-deals-audit" in text
    assert f"== '{RUNTIME_SHA}'" in text
    assert f"== '{PHASE_D_RUNTIME_SHA}'" in text
    assert f"DISPATCHER={PHASE_C_DISPATCHER}" in text
    assert f"DISPATCHER={PHASE_D_DISPATCHER}" in text
    assert "Checkout exact reviewed Phase A runtime" not in text
    assert "issue-307-runtime" not in text

    for operation in ("apply-dual", "verify-dual", "finalize-loopback", "verify-loopback"):
        assert f"needs.authorize.outputs.operation == '{operation}'" in text
    assert "OPERATION: ${{ needs.authorize.outputs.operation }}" in text

    for forbidden in (
        "eval ",
        "bash -c",
        "sh -c",
        "sudo bash",
        "sudo sh",
        "docker compose",
        "docker run",
        "alembic ",
        "psql ",
        "systemctl restart",
        "systemctl stop",
        "systemctl start",
        "ufw allow",
        "ufw deny",
        "ufw delete",
        "cloudflared tunnel",
        "api.cloudflare.com",
        "CF_TUNNEL_TOKEN",
    ):
        assert forbidden not in text


def test_phase_c_verify_operation_is_direct_and_read_only() -> None:
    phase_text = yaml.safe_dump(workflow()["jobs"]["phase-c"], sort_keys=True)
    verify_branch = phase_text.index("if [[ \"$OPERATION\" == 'verify-dual' ]]")
    verify_call = phase_text.index('sudo --non-interactive "$DISPATCHER" verify-dual', verify_branch)
    verify_exit = phase_text.index("exit 0", verify_call)
    check_call = phase_text.index('sudo --non-interactive "$DISPATCHER" check')
    apply_call = phase_text.index('sudo --non-interactive "$DISPATCHER" apply-dual')
    assert verify_branch < verify_call < verify_exit < check_call < apply_call
    verify_slice = phase_text[verify_branch:verify_exit]
    assert 'sudo --non-interactive "$DISPATCHER" apply-dual' not in verify_slice
    assert 'sudo --non-interactive "$DISPATCHER" check' not in verify_slice
    assert "AUTO_ROLLBACK_TO_LAN" not in verify_slice


def test_phase_d_verify_operation_is_direct_and_read_only() -> None:
    phase_text = yaml.safe_dump(workflow()["jobs"]["phase-d"], sort_keys=True)
    verify_branch = phase_text.index("if [[ \"$OPERATION\" == 'verify-loopback' ]]")
    verify_call = phase_text.index('sudo --non-interactive "$DISPATCHER" verify-loopback', verify_branch)
    verify_exit = phase_text.index("exit 0", verify_call)
    preflight_call = phase_text.index('sudo --non-interactive "$DISPATCHER" preflight')
    finalize_call = phase_text.index('sudo --non-interactive "$DISPATCHER" finalize-loopback')
    assert verify_branch < verify_call < verify_exit < preflight_call < finalize_call
    verify_slice = phase_text[verify_branch:verify_exit]
    assert 'sudo --non-interactive "$DISPATCHER" finalize-loopback' not in verify_slice
    assert 'sudo --non-interactive "$DISPATCHER" preflight' not in verify_slice
    assert "AUTO_ROLLBACK_TO_DUAL" not in verify_slice


def test_phase_d_finalize_preflights_then_handles_dual_rollback_marker() -> None:
    phase_text = yaml.safe_dump(workflow()["jobs"]["phase-d"], sort_keys=True)
    preflight = phase_text.index('sudo --non-interactive "$DISPATCHER" preflight')
    finalize = phase_text.index('sudo --non-interactive "$DISPATCHER" finalize-loopback')
    assert preflight < finalize
    assert "HERMES_DEALS_307_LOOPBACK_PREFLIGHT=PASS" in phase_text
    assert "HERMES_DEALS_307_LOOPBACK_FINALIZE=PASS" in phase_text
    assert "AUTO_ROLLBACK_TO_DUAL=PASS" in phase_text
    assert "FINALIZE_FAILED_ROLLBACK_VERIFIED" in phase_text
    assert "FINALIZE_FAILED_STATE_REQUIRES_REVIEW" in phase_text
    assert "DIRECT_LAN_9128_CLOSED=true" in phase_text
    assert "ROLLBACK_TO_DUAL_AVAILABLE=true" in phase_text
    assert "rollback-dual" not in phase_text


def test_self_hosted_jobs_have_no_github_token_checkout_or_secrets() -> None:
    jobs = workflow()["jobs"]
    for name in ("phase-c", "phase-d"):
        phase = jobs[name]
        assert phase["permissions"] == {}
        phase_text = yaml.safe_dump(phase, sort_keys=True)
        assert "github.event.comment.body" not in phase_text
        assert "GH_TOKEN" not in phase_text
        assert "secrets." not in phase_text
        assert "actions/checkout" not in phase_text


def test_reports_are_partitioned_by_phase_operation() -> None:
    jobs = workflow()["jobs"]
    report_c = yaml.safe_dump(jobs["report-c"], sort_keys=True)
    report_d = yaml.safe_dump(jobs["report-d"], sort_keys=True)
    assert "apply-dual" in report_c and "verify-dual" in report_c
    assert "finalize-loopback" not in report_c and "verify-loopback" not in report_c
    assert "finalize-loopback" in report_d and "verify-loopback" in report_d
    assert "apply-dual" not in report_d and "verify-dual" not in report_d


def test_workflow_never_publishes_raw_operator_logs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact" not in text
    for log in (
        "$CHECK_LOG",
        "$APPLY_LOG",
        "$VERIFY_LOG",
        "$RECOVERY_LOG",
        "$PREFLIGHT_LOG",
        "$FINALIZE_LOG",
    ):
        assert f'cat "{log}"' not in text
    assert text.count("Raw operator logs are not published") == 2
    assert "HERMES_DEALS_307_DUAL_BIND_CHECK=PASS" in text
    assert "HERMES_DEALS_307_DUAL_BIND_APPLY=PASS" in text
    assert "HERMES_DEALS_307_DUAL_BIND_VERIFY=PASS" in text
    assert "HERMES_DEALS_307_LOOPBACK_PREFLIGHT=PASS" in text
    assert "HERMES_DEALS_307_LOOPBACK_FINALIZE=PASS" in text
    assert "HERMES_DEALS_307_LOOPBACK_VERIFY=PASS" in text


def test_authorizer_source_contains_no_shell_execution_surface() -> None:
    text = TOOL.read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "shell=True",
        "eval(",
        "exec(",
    ):
        assert forbidden not in text
    assert 'EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"' in text
    assert 'EXPECTED_OWNER_LOGIN = "rozkalnsandris"' in text
    assert "EXPECTED_OWNER_ID = 277435981" in text
    assert "EXPECTED_ISSUE_NUMBER = 307" in text
    assert '"/hermes-307 apply-dual": "apply-dual"' in text
    assert '"/hermes-307 verify-dual": "verify-dual"' in text
    assert '"/hermes-307 finalize-loopback": "finalize-loopback"' in text
    assert '"/hermes-307 verify-loopback": "verify-loopback"' in text
    assert "rollback-dual" not in text
    assert f'RUNTIME_SHA = "{RUNTIME_SHA}"' in text
    assert f'PHASE_D_RUNTIME_SHA = "{PHASE_D_RUNTIME_SHA}"' in text
