from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "github_lidl_gate_d_control.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-gate-d-control.yml"
PLAN = "a" * 64
BRIDGE_SHA = "b" * 40
CURRENT_MAIN = "c" * 40


def load_module():
    spec = importlib.util.spec_from_file_location("github_lidl_gate_d_control", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["github_lidl_gate_d_control"] = module
    spec.loader.exec_module(module)
    return module


def event(body: str) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 24, "pull_request": None},
        "comment": {"id": 123456789, "author_association": "OWNER", "body": body},
    }


def fake_get(url: str, _token: str):
    if url.endswith("/pulls/656"):
        return {
            "merged": True,
            "merged_at": "2026-08-14T18:00:00Z",
            "merge_commit_sha": BRIDGE_SHA,
            "base": {"ref": "main", "repo": {"full_name": "rozkalnsandris/hermes-deals"}},
        }
    if url.endswith(f"/compare/{BRIDGE_SHA}...main"):
        return {"status": "ahead"}
    if url.endswith("/branches/main"):
        return {"commit": {"sha": CURRENT_MAIN}}
    raise AssertionError(url)


@pytest.mark.parametrize("operation", ["activate", "disable", "rollback"])
def test_exact_owner_commands_bind_reviewed_bridge_current_main_and_plan(operation: str):
    module = load_module()
    body = f"/hermes-lidl gate-d {operation} pr=656 sha={CURRENT_MAIN} plan={PLAN}"
    values = module.authorize_event(
        event(body),
        repository="rozkalnsandris/hermes-deals",
        token="token",
        get_json=fake_get,
    )
    assert values == {
        "operation": operation,
        "pr_number": "656",
        "sha": CURRENT_MAIN,
        "plan_fingerprint": PLAN,
        "issue_number": "24",
        "comment_id": "123456789",
        "trigger_actor": "rozkalnsandris",
    }


@pytest.mark.parametrize(
    "body",
    [
        f"/hermes-lidl gate-d activate pr=655 sha={CURRENT_MAIN} plan={PLAN}",
        f"/hermes-lidl gate-d Activate pr=656 sha={CURRENT_MAIN} plan={PLAN}",
        f"/hermes-lidl gate-d activate pr=656 plan={PLAN}",
        f"/hermes-lidl gate-d activate pr=656 sha={'C' * 40} plan={PLAN}",
        f"/hermes-lidl gate-d activate pr=656 sha={'c' * 39} plan={PLAN}",
        f"/hermes-lidl gate-d activate pr=656 sha={CURRENT_MAIN} plan={'A' * 64}",
        f"/hermes-lidl gate-d activate pr=656 sha={CURRENT_MAIN} plan={'a' * 63}",
        f"/hermes-lidl gate-d activate pr=656 sha={CURRENT_MAIN} plan={PLAN} extra",
        "/hermes-lidl gate-d activate pr=656 sha=$(id) plan=$(id)",
    ],
)
def test_command_parser_fails_closed(body: str):
    module = load_module()
    with pytest.raises(module.BridgeAuthorizationError):
        module.parse_comment(body)


def test_authorizer_rejects_wrong_owner_issue_or_association():
    module = load_module()
    body = f"/hermes-lidl gate-d disable pr=656 sha={CURRENT_MAIN} plan={PLAN}"
    bad = event(body)
    bad["sender"]["id"] = 1
    with pytest.raises(module.BridgeAuthorizationError, match="allowlisted owner"):
        module.authorize_event(bad, repository=module.EXPECTED_REPOSITORY, token="x", get_json=fake_get)

    bad = event(body)
    bad["issue"]["number"] = 25
    with pytest.raises(module.BridgeAuthorizationError, match="issue #24"):
        module.authorize_event(bad, repository=module.EXPECTED_REPOSITORY, token="x", get_json=fake_get)

    bad = event(body)
    bad["comment"]["author_association"] = "MEMBER"
    with pytest.raises(module.BridgeAuthorizationError, match="repository owner"):
        module.authorize_event(bad, repository=module.EXPECTED_REPOSITORY, token="x", get_json=fake_get)


def test_authorizer_requires_merged_reachable_control_bridge():
    module = load_module()
    body = f"/hermes-lidl gate-d rollback pr=656 sha={CURRENT_MAIN} plan={PLAN}"

    def not_merged(url: str, _token: str):
        if url.endswith("/pulls/656"):
            return {"merged": False, "base": {"ref": "main", "repo": {"full_name": module.EXPECTED_REPOSITORY}}}
        raise AssertionError(url)

    with pytest.raises(module.BridgeAuthorizationError, match="not merged"):
        module.authorize_event(event(body), repository=module.EXPECTED_REPOSITORY, token="x", get_json=not_merged)

    def diverged(url: str, _token: str):
        if url.endswith("/pulls/656"):
            return {
                "merged": True,
                "merged_at": "2026-08-14T18:00:00Z",
                "merge_commit_sha": BRIDGE_SHA,
                "base": {"ref": "main", "repo": {"full_name": module.EXPECTED_REPOSITORY}},
            }
        if url.endswith(f"/compare/{BRIDGE_SHA}...main"):
            return {"status": "diverged"}
        raise AssertionError(url)

    with pytest.raises(module.BridgeAuthorizationError, match="not reachable"):
        module.authorize_event(event(body), repository=module.EXPECTED_REPOSITORY, token="x", get_json=diverged)


def test_authorizer_rejects_stale_registration_sha():
    module = load_module()
    stale = "d" * 40
    body = f"/hermes-lidl gate-d activate pr=656 sha={stale} plan={PLAN}"
    with pytest.raises(module.BridgeAuthorizationError, match="exact current main"):
        module.authorize_event(event(body), repository=module.EXPECTED_REPOSITORY, token="x", get_json=fake_get)


def test_github_output_rejects_newlines(tmp_path: Path):
    module = load_module()
    values = module.authorize_event(
        event(f"/hermes-lidl gate-d activate pr=656 sha={CURRENT_MAIN} plan={PLAN}"),
        repository=module.EXPECTED_REPOSITORY,
        token="x",
        get_json=fake_get,
    )
    values["trigger_actor"] = "owner\ninjected=true"
    with pytest.raises(module.BridgeAuthorizationError, match="newline"):
        module.write_github_outputs(tmp_path / "out", values)


def test_workflow_keeps_untrusted_comment_off_self_hosted_shell():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:" in source
    assert "github.event.issue.number == 24" in source
    assert "github.event.sender.id == 277435981" in source
    assert "github.event.comment.author_association == 'OWNER'" in source
    assert "startsWith(github.event.comment.body, '/hermes-lidl gate-d ')" in source
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2" in source
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0" in source
    assert "persist-credentials: false" in source

    self_hosted = source.split("  control:\n", 1)[1]
    assert "hermes-deals-audit" in self_hosted
    assert "permissions: {}" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "github.event.comment.body" not in self_hosted
    assert "GH_TOKEN" not in self_hosted
    assert 'sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-d-control' in self_hosted
    assert "/bin/bash -c" not in self_hosted
    assert "systemctl" not in source
