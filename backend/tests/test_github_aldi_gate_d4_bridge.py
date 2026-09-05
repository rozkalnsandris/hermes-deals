from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_aldi_gate_d4_bridge.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-aldi-gate-d4-bridge.yml"

SPEC = importlib.util.spec_from_file_location("github_aldi_gate_d4_bridge_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

RUNTIME_PR = 646
RUNTIME_SHA = "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"
COMMAND = f"/hermes-aldi gate-d4 pr={RUNTIME_PR}"


def valid_event(body: str = COMMAND) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 631},
        "comment": {"id": 5274000000, "body": body, "author_association": "OWNER"},
    }


def fake_github(url: str, _token: str):
    if url.endswith(f"/pulls/{RUNTIME_PR}"):
        return {
            "merged": True,
            "merged_at": "2026-08-13T20:38:00Z",
            "merge_commit_sha": RUNTIME_SHA,
            "base": {"ref": "main", "repo": {"full_name": "rozkalnsandris/hermes-deals"}},
        }
    if f"/compare/{RUNTIME_SHA}...main" in url:
        return {"status": "ahead"}
    raise AssertionError(f"unexpected URL: {url}")


def test_exact_gate_d4_command_parses() -> None:
    command = MODULE.parse_comment(COMMAND)
    assert command.operation == "aldi-gate-d4"
    assert command.pr_number == RUNTIME_PR


@pytest.mark.parametrize(
    "body",
    [
        f"{COMMAND}\necho pwned",
        f"{COMMAND} extra=1",
        "/hermes-aldi gate-d4 pr=637",
        "/hermes-aldi gate-d4 pr=0",
        f"/hermes-aldi gate-d3 pr={RUNTIME_PR}",
        f"/hermes-aldi deploy pr={RUNTIME_PR}",
    ],
)
def test_parser_rejects_non_allowlisted_or_injected_commands(body: str) -> None:
    with pytest.raises(MODULE.BridgeAuthorizationError):
        MODULE.parse_comment(body)


def test_authorization_binds_owner_issue_runtime_pr_and_exact_sha() -> None:
    result = MODULE.authorize_event(
        valid_event(), repository="rozkalnsandris/hermes-deals", token="test", get_json=fake_github
    )
    assert result == {
        "operation": "aldi-gate-d4",
        "pr_number": str(RUNTIME_PR),
        "sha": RUNTIME_SHA,
        "issue_number": "631",
        "comment_id": "5274000000",
        "trigger_actor": "rozkalnsandris",
    }


def test_authorization_rejects_non_owner_or_non_owner_association() -> None:
    event = valid_event()
    event["sender"]["id"] = 1
    with pytest.raises(MODULE.BridgeAuthorizationError, match="allowlisted owner"):
        MODULE.authorize_event(event, repository="rozkalnsandris/hermes-deals", token="test", get_json=fake_github)

    event = valid_event()
    event["comment"]["author_association"] = "MEMBER"
    with pytest.raises(MODULE.BridgeAuthorizationError, match="association"):
        MODULE.authorize_event(event, repository="rozkalnsandris/hermes-deals", token="test", get_json=fake_github)


def test_authorization_rejects_other_issue_pr_comment_or_wrong_repository() -> None:
    event = valid_event()
    event["issue"]["number"] = 632
    with pytest.raises(MODULE.BridgeAuthorizationError, match="#631"):
        MODULE.authorize_event(event, repository="rozkalnsandris/hermes-deals", token="test", get_json=fake_github)

    event = valid_event()
    event["issue"]["pull_request"] = {"url": "https://example.invalid"}
    with pytest.raises(MODULE.BridgeAuthorizationError, match="only on issues"):
        MODULE.authorize_event(event, repository="rozkalnsandris/hermes-deals", token="test", get_json=fake_github)

    with pytest.raises(MODULE.BridgeAuthorizationError, match="unexpected repository"):
        MODULE.authorize_event(valid_event(), repository="other/repo", token="test", get_json=fake_github)


def test_authorization_rejects_unmerged_drifted_or_unreachable_runtime() -> None:
    def unmerged(url: str, _token: str):
        assert url.endswith(f"/pulls/{RUNTIME_PR}")
        return {"merged": False, "merged_at": None}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="not merged"):
        MODULE.authorize_event(valid_event(), repository="rozkalnsandris/hermes-deals", token="test", get_json=unmerged)

    def drift(url: str, token: str):
        if url.endswith(f"/pulls/{RUNTIME_PR}"):
            payload = fake_github(url, token)
            payload["merge_commit_sha"] = "0" * 40
            return payload
        raise AssertionError(url)

    with pytest.raises(MODULE.BridgeAuthorizationError, match="does not match reviewed"):
        MODULE.authorize_event(valid_event(), repository="rozkalnsandris/hermes-deals", token="test", get_json=drift)

    def diverged(url: str, token: str):
        if url.endswith(f"/pulls/{RUNTIME_PR}"):
            return fake_github(url, token)
        return {"status": "diverged"}

    with pytest.raises(MODULE.BridgeAuthorizationError, match="not reachable"):
        MODULE.authorize_event(valid_event(), repository="rozkalnsandris/hermes-deals", token="test", get_json=diverged)


def test_workflow_is_exact_owner_issue_comment_and_self_hosted_job_has_no_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]

    assert "github.event.issue.number == 631" in text
    assert "github.actor == 'rozkalnsandris'" in text
    assert "github.event.comment.author_association == 'OWNER'" in text
    assert f"github.event.comment.body == '{COMMAND}'" in text
    assert "python tools/github_aldi_gate_d4_bridge.py" in text
    assert "permissions: {}" in text
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in text
    assert text.count("actions/checkout@") == 1

    audit_job = parsed["jobs"]["audit"]
    audit_steps = audit_job["steps"]
    assert all("actions/checkout@" not in str(step) for step in audit_steps)
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-aldi-gate-d4-backup-discovery" in text
    assert RUNTIME_SHA not in text

    for forbidden in (
        "workflow_dispatch:",
        "pull_request:",
        "push:",
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


def test_workflow_validates_v2_exact_file_capability_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'result.get("request_schema_version")' in text
    assert 'result.get("designated_root_count")' in text
    assert 'result.get("designated_file_count")' in text
    assert 'result.get("designated_input_count")' in text
    assert 'safety.get("explicit_inputs_only") is not True' in text
    assert 'safety.get("explicit_roots_only") is not (file_count == 0)' in text
    assert 'safety.get("exact_file_allowlist_enabled") is not (file_count > 0)' in text
    assert 'safety.get("strict_49_plus_41_frozen_contract_unchanged") is not True' in text


def test_workflow_never_accepts_backup_inputs_from_comment_or_event() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert f"{COMMAND} roots=" not in text
    assert f"{COMMAND} root=" not in text
    assert f"{COMMAND} files=" not in text
    assert f"{COMMAND} file=" not in text
    assert "github.event.comment.body |" not in text
    assert "github.event.comment.body" in text
    assert COMMAND in text
    for safety in (
        "raw_request_exported",
        "network_acquisition_authorized",
        "archive_extraction_authorized",
        "production_database_write_authorized",
        "production_deployment_authorized",
        "historical_recovery_binding_authorized",
        "irrecoverable_decision_recording_authorized",
    ):
        assert safety in text


def test_authorizer_has_no_shell_execution_surface_and_is_exactly_bound() -> None:
    text = TOOL.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "shell=True", "eval(", "exec("):
        assert forbidden not in text
    assert "COMMAND_RE.fullmatch" in text
    assert 'EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"' in text
    assert "EXPECTED_OWNER_ID = 277435981" in text
    assert "EXPECTED_ISSUE_NUMBER = 631" in text
    assert f"EXPECTED_RUNTIME_PR = {RUNTIME_PR}" in text
    assert f'EXPECTED_RUNTIME_SHA = "{RUNTIME_SHA}"' in text
