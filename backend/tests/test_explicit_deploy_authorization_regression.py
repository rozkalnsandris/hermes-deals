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


def test_manual_and_control_deploys_share_one_fail_closed_authorizer() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    helper = AUTHORIZER.read_text(encoding="utf-8")
    deploy = yaml.safe_load(text)
    inputs = _workflow_trigger(deploy)["workflow_dispatch"]["inputs"]

    assert inputs["target_sha"]["required"] is False
    assert inputs["confirmation"]["required"] is False
    assert inputs["authorization_issue"]["required"] is False
    assert inputs["authorization_comment_id"]["required"] is False
    assert inputs["control_action"]["required"] is False
    assert inputs["expected_main_sha"]["required"] is False
    assert inputs["control_request_id"]["required"] is False

    for marker in (
        "ORIGINAL_ACTOR: ${{ github.actor }}",
        "ORIGINAL_ACTOR_ID: ${{ github.actor_id }}",
        "TRIGGERING_ACTOR: ${{ github.triggering_actor }}",
        "RUN_ATTEMPT: ${{ github.run_attempt }}",
        "CONTROL_ACTION: ${{ inputs.control_action }}",
        "EXPECTED_MAIN_SHA: ${{ inputs.expected_main_sha }}",
        "CONTROL_REQUEST_ID: ${{ inputs.control_request_id }}",
        'event_ref=os.environ["EVENT_REF"]',
        "from tools.github_deploy_main_authorization import authorize_deploy_main",
        "AUTHORIZATION_ISSUE: ${{ inputs.authorization_issue }}",
        "AUTHORIZATION_COMMENT_ID: ${{ inputs.authorization_comment_id }}",
        "/usr/local/sbin/hermes-deals-deploy-main",
    ):
        assert marker in text

    for marker in (
        'if actor == EXPECTED_OWNER and triggering_actor == EXPECTED_OWNER:',
        'manual owner dispatch must not include Control inputs',
        'elif actor == CONTROL_APP_ACTOR and triggering_actor == CONTROL_APP_ACTOR:',
        'CONTROL_APP_ACTOR_ID = 316106438',
        'Control App dispatch reruns are not authorized',
        'Control App action is not LIVE',
        'mode != "control_app" and confirmation != f"DEPLOY {requested_sha}"',
        'mode in {"owner_comment_via_bot", "control_app"}',
    ):
        assert marker in helper
