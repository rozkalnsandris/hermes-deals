from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "github_aldi_gate_d4_encrypted_bridge.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-aldi-gate-d4-encrypted-bridge.yml"


def load_module():
    spec = importlib.util.spec_from_file_location("github_aldi_gate_d4_encrypted_bridge_tested", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(body="/hermes-aldi gate-d4-encrypted pr=646"):
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 679, "pull_request": None},
        "comment": {"id": 123, "body": body, "author_association": "OWNER"},
    }


def getter(url, _token):
    if "/pulls/646" in url:
        return {
            "merged": True,
            "merged_at": "2026-08-15T00:00:00Z",
            "merge_commit_sha": "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e",
            "base": {"ref": "main", "repo": {"full_name": "rozkalnsandris/hermes-deals"}},
        }
    if "/compare/" in url:
        return {"status": "ahead"}
    raise AssertionError(url)


def test_exact_owner_command_authorizes_reviewed_runtime():
    module = load_module()
    values = module.authorize_event(event(), repository="rozkalnsandris/hermes-deals", token="x", get_json=getter)
    assert values["operation"] == "aldi-gate-d4-encrypted"
    assert values["sha"] == "8b9b7e66c754cb7f8a82d4d67503d59fd2ff000e"


def test_wrong_issue_or_command_fails_closed():
    module = load_module()
    wrong = event()
    wrong["issue"]["number"] = 631
    with pytest.raises(module.BridgeAuthorizationError):
        module.authorize_event(wrong, repository="rozkalnsandris/hermes-deals", token="x", get_json=getter)
    with pytest.raises(module.BridgeAuthorizationError):
        module.authorize_event(event("/hermes-aldi gate-d4 pr=646"), repository="rozkalnsandris/hermes-deals", token="x", get_json=getter)


def test_workflow_is_exact_owner_gated_and_sanitized():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.issue.number == 679" in source
    assert "github.actor == 'rozkalnsandris'" in source
    assert "github.event.comment.body == '/hermes-aldi gate-d4-encrypted pr=646'" in source
    assert "permissions: {}" in source
    assert "plaintext_exported" in source
    assert "age_identity_exported" in source
    assert "READY_FOR_IRRECOVERABLE_DECISION" not in source
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in source
