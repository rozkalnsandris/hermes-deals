from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_aldi_gate_d3_bridge.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-aldi-gate-d3-bridge.yml"

SPEC = importlib.util.spec_from_file_location("github_aldi_gate_d3_bridge_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def valid_event(body: str = "/hermes-aldi gate-d3 pr=281") -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 290},
        "comment": {"id": 5269151565, "body": body},
    }


def fake_github(url: str, _token: str):
    if url.endswith("/pulls/281"):
        return {
            "merged": True,
            "merged_at": "2026-08-07T11:07:28Z",
            "merge_commit_sha": "530a6b6d2b31f635f182788ccace01003b1cbc7d",
            "base": {
                "ref": "main",
                "repo": {"full_name": "rozkalnsandris/hermes-deals"},
            },
        }
    if "/compare/530a6b6d2b31f635f182788ccace01003b1cbc7d...main" in url:
        return {"status": "ahead"}
    raise AssertionError(f"unexpected URL: {url}")


def test_exact_gate_d3_command_parses() -> None:
    command = MODULE.parse_comment("/hermes-aldi gate-d3 pr=281")
    assert command.operation == "aldi-gate-d3"
    assert command.pr_number == 281


@pytest.mark.parametrize(
    "body",
    [
        "/hermes-aldi gate-d3 pr=281\necho pwned",
        "/hermes-aldi gate-d3 pr=281 extra=1",
        "/hermes-aldi gate-d3 pr=280",
        "/hermes-aldi gate-d3 pr=0",
        "/hermes-aldi deploy pr=281",
        "/hermes-bridge aldi-gate-d3 pr=281",
    ],
)
def test_parser_rejects_non_allowlisted_or_injected_commands(body: str) -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError):
        MODULE.parse_comment(body)


def test_authorization_binds_owner_issue_runtime_pr_and_exact_sha() -> None:
    result = MODULE.authorize_event(
        valid_event(),
        repository="rozkalnsandris/hermes-deals",
        token="test-token",
        get_json=fake_github,
    )
    assert result == {
        "operation": "aldi-gate-d3",
        "pr_number": "281",
        "sha": "530a6b6d2b31f635f182788ccace01003b1cbc7d",
        "issue_number": "290",
        "comment_id": "5269151565",
        "trigger_actor": "rozkalnsandris",
    }


@pytest.mark.parametrize(("field", "value"), [("login", "other"), ("id", 1)])
def test_authorization_rejects_non_owner(field: str, value: object) -> None:
    event = valid_event()
    event["sender"][field] = value
    with pytest.raises(MODULE.BridgeAuthorizationError, match="allowlisted owner"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorization_rejects_other_issue() -> None:
    event = valid_event()
    event["issue"]["number"] = 291
    with pytest.raises(MODULE.BridgeAuthorizationError, match="#290"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorization_rejects_pr_comment() -> None:
    event = valid_event()
    event["issue"]["pull_request"] = {"url": "https://example.invalid/pr/1"}
    with pytest.raises(MODULE.BridgeAuthorizationError, match="only on issues"):
        MODULE.authorize_event(
            event,
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake_github,
        )


def test_authorization_rejects_wrong_repository() -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError, match="unexpected repository"):
        MODULE.authorize_event(
            valid_event(), repository="other/repo", token="test-token", get_json=fake_github
        )


def test_authorization_rejects_unmerged_runtime_pr() -> None:
    def fake(url: str, _token: str):
        assert url.endswith("/pulls/281")
        return {"merged": False, "merged_at": None}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="not merged"):
        MODULE.authorize_event(
            valid_event(),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_authorization_rejects_runtime_sha_drift() -> None:
    def fake(url: str, token: str):
        if url.endswith("/pulls/281"):
            payload = fake_github(url, token)
            payload["merge_commit_sha"] = "0" * 40
            return payload
        raise AssertionError(url)

    with pytest.raises(MODULE.BridgeAuthorizationError, match="does not match reviewed"):
        MODULE.authorize_event(
            valid_event(),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_authorization_rejects_runtime_not_reachable_from_main() -> None:
    def fake(url: str, token: str):
        if url.endswith("/pulls/281"):
            return fake_github(url, token)
        return {"status": "diverged"}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="not reachable"):
        MODULE.authorize_event(
            valid_event(),
            repository="rozkalnsandris/hermes-deals",
            token="test-token",
            get_json=fake,
        )


def test_output_writer_rejects_newline(tmp_path: Path) -> None:
    values = MODULE.authorize_event(
        valid_event(),
        repository="rozkalnsandris/hermes-deals",
        token="test-token",
        get_json=fake_github,
    )
    values["trigger_actor"] = "rozkalnsandris\nunsafe=value"
    with pytest.raises(MODULE.BridgeAuthorizationError, match="unsafe newline"):
        MODULE.write_github_outputs(tmp_path / "out", values)


def test_workflow_has_only_issue_comment_trigger_and_fixed_read_only_dispatch_surface() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]

    assert "workflow_dispatch:" not in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "github.event.issue.number == 290" in text
    assert "python tools/github_aldi_gate_d3_bridge.py" in text
    assert (
        "sudo --non-interactive /usr/local/sbin/hermes-deals-aldi-gate-d3-recovery-inventory"
        in text
    )
    assert "install-aldi-gate-d3-recovery-inventory.py" not in text
    assert "hermes-deals-audit-register" not in text
    assert "permissions: {}" in text
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in text

    for forbidden in (
        "eval ",
        "bash -c",
        "sh -c",
        "docker compose",
        "alembic ",
        "psql ",
        "systemctl ",
        "curl ",
        "wget ",
        "git reset",
        "git checkout",
    ):
        assert forbidden not in text

    for safety_flag in (
        "raw_evidence_exported",
        "raw_stderr_exported",
        "archive_extraction_authorized",
        "corpus_mutation_authorized",
        "review_write_authorized",
        "production_database_write_authorized",
        "production_deploy_authorized",
        "scheduler_change_authorized",
    ):
        assert safety_flag in text


def test_tool_has_no_shell_execution_surface_and_is_exactly_bound() -> None:
    text = TOOL.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "shell=True", "eval(", "exec("):
        assert forbidden not in text
    assert "COMMAND_RE.fullmatch" in text
    assert 'EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"' in text
    assert 'EXPECTED_OWNER_LOGIN = "rozkalnsandris"' in text
    assert "EXPECTED_OWNER_ID = 277435981" in text
    assert "EXPECTED_ISSUE_NUMBER = 290" in text
    assert "EXPECTED_RUNTIME_PR = 281" in text
    assert 'EXPECTED_RUNTIME_SHA = "530a6b6d2b31f635f182788ccace01003b1cbc7d"' in text
