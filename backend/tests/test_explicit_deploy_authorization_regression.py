from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-main.yml"
AUTHORIZER = ROOT / "tools" / "github_deploy_main_authorization.py"


def _workflow_trigger(payload: dict) -> dict:
    # PyYAML 1.1 may parse the key `on` as boolean True.
    return payload.get("on") or payload.get(True) or {}


def test_successful_main_ci_cannot_trigger_production_deploy() -> None:
    ci = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    deploy = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))

    assert ci["name"] == "Hermes Deals CI checks"
    trigger = _workflow_trigger(deploy)
    assert set(trigger) == {"workflow_dispatch"}
    assert "workflow_run" not in trigger


def test_manual_and_control_deploys_share_existing_explicit_input_contract() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    helper = AUTHORIZER.read_text(encoding="utf-8")
    deploy = yaml.safe_load(text)
    inputs = _workflow_trigger(deploy)["workflow_dispatch"]["inputs"]

    assert set(inputs) == {
        "target_sha",
        "confirmation",
        "authorization_issue",
        "authorization_comment_id",
    }
    assert inputs["target_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True
    assert inputs["authorization_issue"]["required"] is False
    assert inputs["authorization_comment_id"]["required"] is False

    for marker in (
        "ORIGINAL_ACTOR: ${{ github.actor }}",
        "TRIGGERING_ACTOR: ${{ github.triggering_actor }}",
        'event_ref=os.environ["EVENT_REF"]',
        "from tools.github_deploy_main_authorization import authorize_deploy_main",
        "AUTHORIZATION_ISSUE: ${{ inputs.authorization_issue }}",
        "AUTHORIZATION_COMMENT_ID: ${{ inputs.authorization_comment_id }}",
        "/usr/local/sbin/hermes-deals-deploy-main",
    ):
        assert marker in text

    for marker in (
        'CONTROL_APP_ACTOR = "rozkalns-control[bot]"',
        "CONTROL_APP_ACTOR_ID = 316106438",
        'elif actor == CONTROL_APP_ACTOR and triggering_actor == CONTROL_APP_ACTOR:',
        'Control App dispatch must not include comment authorization',
        'https://api.github.com/users/{encoded_actor}',
        'principal.get("id") != CONTROL_APP_ACTOR_ID',
        'confirmation != f"DEPLOY {target_sha}"',
        'mode in {"owner_comment_via_bot", "control_app"}',
    ):
        assert marker in helper
