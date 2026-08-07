from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_gate_b_plan_bridge.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-gate-b-plan-bridge.yml"

SPEC = importlib.util.spec_from_file_location("github_gate_b_plan_bridge_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_event(body: str | None = None) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 287},
        "comment": {
            "id": 5221666004,
            "body": body
            or "/hermes-gate-b-plan pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=1",
        },
    }


def fake_github(url: str, _token: str):
    sha = "90bdaee59eb3c385ca1b801746d8acbd58b5e263"
    if url.endswith("/pulls/209"):
        return {
            "merged": True,
            "merged_at": "2026-08-06T14:51:28Z",
            "merge_commit_sha": sha,
            "base": {
                "ref": "main",
                "repo": {"full_name": "rozkalnsandris/hermes-deals"},
            },
        }
    if f"/compare/{sha}...main" in url:
        return {"status": "ahead"}
    if "tools/lidl_gate_b_freeze_plan.py" in url:
        return {"sha": MODULE.EXPECTED_PLAN_BLOB}
    if "tools/lidl_gate_b_freeze_apply.py" in url:
        return {"sha": MODULE.EXPECTED_APPLY_BLOB}
    raise AssertionError(f"unexpected URL: {url}")


def test_exact_allowlisted_command_parses() -> None:
    command = MODULE.parse_comment(
        "/hermes-gate-b-plan pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=1"
    )
    assert command.pr_number == 209
    assert command.gate_a_run_id == 31215491519
    assert command.gate_a_run_attempt == 1


@pytest.mark.parametrize(
    "body",
    [
        "/hermes-gate-b-plan pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=1\necho pwned",
        "/hermes-gate-b-plan pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=1 extra=1",
        "/hermes-gate-b-plan pr=0 gate_a_run_id=31215491519 gate_a_run_attempt=1",
        "/hermes-gate-b-plan pr=209 gate_a_run_id=0 gate_a_run_attempt=1",
        "/hermes-gate-b-plan pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=0",
        "/hermes-gate-b-plan pr=209 gate_a_run_id=abc gate_a_run_attempt=1",
        "/hermes-gate-b-apply pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=1",
        "/hermes-bridge lidl-gate-b-plan pr=209 gate_a_run_id=31215491519 gate_a_run_attempt=1",
    ],
)
def test_parser_fails_closed_on_non_allowlisted_or_injected_text(body: str) -> None:
    with pytest.raises(MODULE.GateBPlanBridgeAuthorizationError):
        MODULE.parse_comment(body)


def test_authorize_event_binds_owner_issue_runtime_blobs_and_retained_run() -> None:
    result = MODULE.authorize_event(
        valid_event(),
        repository="rozkalnsandris/hermes-deals",
        token="test-token",
        get_json=fake_github,
    )
    assert result == {
        "pr_number": "209",
        "sha": "90bdaee59eb3c385ca1b801746d8acbd58b5e263",
        "gate_a_run_id": "31215491519",
        "gate_a_run_attempt": "1",
        "gate_a_run_key": "lidl-gate-a-31215491519-1",
        "issue_number": "287",
        "comment_id": "5221666004",
        "trigger_actor": "rozkalnsandris",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [("login", "someone-else"), ("id", 1)],
)
def test_authorize_event_rejects_non_owner_sender(field: str, value: object) -> None:
    event = valid_event()
    event["sender"][field] = value
    with pytest.raises(MODULE.GateBPlanBridgeAuthorizationError, match="allowlisted"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorize_event_rejects_pull_request_comments() -> None:
    event = valid_event()
    event["issue"]["pull_request"] = {"url": "https://example.invalid/pr/1"}
    with pytest.raises(MODULE.GateBPlanBridgeAuthorizationError, match="only on issues"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorize_event_rejects_unmerged_runtime_pr() -> None:
    def fake(url: str, _token: str):
        assert url.endswith("/pulls/209")
        return {"merged": False, "merged_at": None}

    with pytest.raises(MODULE.GateBPlanBridgeAuthorizationError, match="only merged"):
        MODULE.authorize_event(
            valid_event(),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_authorize_event_rejects_current_main_gate_b_blob_drift() -> None:
    def fake(url: str, token: str):
        if "tools/lidl_gate_b_freeze_plan.py" in url and "?ref=main" in url:
            return {"sha": "0" * 40}
        return fake_github(url, token)

    with pytest.raises(
        MODULE.GateBPlanBridgeAuthorizationError,
        match="current main Gate B blob drift",
    ):
        MODULE.authorize_event(
            valid_event(),
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
    values["gate_a_run_key"] = "lidl-gate-a-1-1\nunsafe=value"
    with pytest.raises(MODULE.GateBPlanBridgeAuthorizationError, match="unsafe newline"):
        MODULE.write_github_outputs(tmp_path / "out", values)


def test_workflow_is_issue_comment_only_and_passes_no_raw_comment_to_rpi5_shell() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]

    assert "workflow_dispatch:" not in text
    assert "push:" not in text
    assert "pull_request:" not in text
    assert text.count("github.event.comment.body") == 1
    assert "startsWith(github.event.comment.body, '/hermes-gate-b-plan ')" in text
    assert "python tools/github_gate_b_plan_bridge.py" in text
    assert (
        "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-b-plan-dispatch"
        in text
    )
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 30" in text
    assert 'state not in {"READY_TO_FREEZE", "BLOCKED"}' in text
    assert 'state == "BLOCKED" and runner_rc != 30' in text

    for forbidden in (
        "eval ",
        "bash -c",
        "sh -c",
        "docker compose",
        "alembic ",
        "psql ",
        "systemctl ",
        "lidl-gate-b-freeze-apply",
        "corpus_write_authorized\": true",
    ):
        assert forbidden not in text

    for safety_flag in (
        "corpus_write_authorized",
        "parser_scan_authorized",
        "database_write_authorized",
        "review_write_authorized",
        "production_publish_authorized",
        "production_deploy_authorized",
        "systemd_change_authorized",
        "automatic_retry_authorized",
        "gate_c_d_authorized",
    ):
        assert safety_flag in text


def test_tool_source_contains_no_shell_execution_surface() -> None:
    text = TOOL.read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "shell=True",
        "eval(",
        "exec(",
    ):
        assert forbidden not in text
    assert "COMMAND_RE.fullmatch" in text
    assert 'EXPECTED_OWNER_LOGIN = "rozkalnsandris"' in text
    assert "EXPECTED_OWNER_ID = 277435981" in text
    assert MODULE.EXPECTED_PLAN_BLOB in text
    assert MODULE.EXPECTED_APPLY_BLOB in text
