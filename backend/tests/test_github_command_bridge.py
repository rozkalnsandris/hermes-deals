from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_command_bridge.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-command-bridge.yml"

SPEC = importlib.util.spec_from_file_location("github_command_bridge_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_event(body: str | None = None) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 287},
        "comment": {
            "id": 5221548805,
            "body": body
            or "/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-08-07 use_previous=false",
        },
    }


def fake_github(url: str, _token: str):
    if url.endswith("/pulls/299"):
        return {
            "merged": True,
            "merged_at": "2026-08-07T18:59:02Z",
            "merge_commit_sha": "9c7d50502f229cc9c733b3fcd8f7a48a5e788e42",
            "base": {
                "ref": "main",
                "repo": {"full_name": "rozkalnsandris/hermes-deals"},
            },
        }
    if "/compare/9c7d50502f229cc9c733b3fcd8f7a48a5e788e42...main" in url:
        return {"status": "ahead"}
    raise AssertionError(f"unexpected URL: {url}")


def test_exact_allowlisted_command_parses() -> None:
    command = MODULE.parse_comment(
        "/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-08-07 use_previous=false"
    )
    assert command.operation == "lidl-gate-a"
    assert command.pr_number == 299
    assert command.target == "current"
    assert command.as_of == "2026-08-07"
    assert command.use_previous == "false"


@pytest.mark.parametrize(
    "body",
    [
        "/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-08-07 use_previous=false\necho pwned",
        "/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-08-07 use_previous=false extra=1",
        "/hermes-bridge deploy pr=299 target=current as_of=2026-08-07 use_previous=false",
        "/hermes-bridge lidl-gate-a pr=299 target=anything as_of=2026-08-07 use_previous=false",
        "/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-02-30 use_previous=false",
        "/hermes-bridge lidl-gate-a pr=0 target=current as_of=2026-08-07 use_previous=false",
        "/hermes-bridge lidl-gate-a pr=299 target=current as_of=2026-08-07 use_previous=yes",
    ],
)
def test_parser_fails_closed_on_non_allowlisted_or_injected_text(body: str) -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError):
        MODULE.parse_comment(body)


def test_authorize_event_binds_owner_issue_merged_pr_and_reachable_sha() -> None:
    result = MODULE.authorize_event(
        valid_event(),
        repository="rozkalnsandris/hermes-deals",
        token="test-token",
        get_json=fake_github,
    )
    assert result == {
        "operation": "lidl-gate-a",
        "pr_number": "299",
        "sha": "9c7d50502f229cc9c733b3fcd8f7a48a5e788e42",
        "target": "current",
        "as_of": "2026-08-07",
        "use_previous": "false",
        "issue_number": "287",
        "comment_id": "5221548805",
        "trigger_actor": "rozkalnsandris",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("login", "someone-else"),
        ("id", 1),
    ],
)
def test_authorize_event_rejects_non_owner_sender(field: str, value: object) -> None:
    event = valid_event()
    event["sender"][field] = value
    with pytest.raises(MODULE.BridgeAuthorizationError, match="allowlisted"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorize_event_rejects_pull_request_comments() -> None:
    event = valid_event()
    event["issue"]["pull_request"] = {"url": "https://example.invalid/pr/1"}
    with pytest.raises(MODULE.BridgeAuthorizationError, match="only on issues"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorize_event_rejects_wrong_repository() -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError, match="unexpected repository"):
        MODULE.authorize_event(
            valid_event(),
            repository="other/repo",
            token="test-token",
            get_json=fake_github,
        )


def test_authorize_event_rejects_unmerged_runtime_pr() -> None:
    def fake(url: str, _token: str):
        assert url.endswith("/pulls/299")
        return {"merged": False, "merged_at": None}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="only merged"):
        MODULE.authorize_event(
            valid_event(),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_authorize_event_rejects_runtime_pr_not_merged_to_main() -> None:
    def fake(url: str, _token: str):
        assert url.endswith("/pulls/299")
        return {
            "merged": True,
            "merged_at": "2026-08-07T18:59:02Z",
            "merge_commit_sha": "9c7d50502f229cc9c733b3fcd8f7a48a5e788e42",
            "base": {
                "ref": "feature",
                "repo": {"full_name": "rozkalnsandris/hermes-deals"},
            },
        }

    with pytest.raises(MODULE.BridgeAuthorizationError, match="repository main"):
        MODULE.authorize_event(
            valid_event(),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_authorize_event_rejects_sha_not_reachable_from_main() -> None:
    def fake(url: str, token: str):
        if url.endswith("/pulls/299"):
            return fake_github(url, token)
        return {"status": "diverged"}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="not reachable"):
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
    values["target"] = "current\nunsafe=value"
    with pytest.raises(MODULE.BridgeAuthorizationError, match="unsafe newline"):
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
    assert "python tools/github_command_bridge.py" in text
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch" in text
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 30" in text

    for forbidden in (
        "eval ",
        "bash -c",
        "sh -c",
        "docker compose",
        "alembic ",
        "psql ",
        "systemctl ",
        "production_apply_authorized: True",
    ):
        assert forbidden not in text

    for safety_flag in (
        "corpus_write_authorized",
        "database_write_authorized",
        "review_write_authorized",
        "production_publish_authorized",
        "production_deploy_authorized",
        "systemd_change_authorized",
        "bounded_retry_authorized",
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
