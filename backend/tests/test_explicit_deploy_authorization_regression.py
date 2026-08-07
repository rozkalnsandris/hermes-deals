from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-main.yml"


def _workflow_trigger(payload: dict) -> dict:
    # PyYAML 1.1 may parse the key `on` as boolean True.
    return payload.get("on") or payload.get(True) or {}


def test_successful_main_ci_cannot_match_legacy_auto_deploy_listener() -> None:
    ci = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    deploy = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))

    ci_name = ci["name"]
    trigger = _workflow_trigger(deploy)
    workflow_run = trigger.get("workflow_run") or {}
    listened_workflows = workflow_run.get("workflows") or []

    assert ci_name == "Hermes Deals CI checks"
    assert ci_name not in listened_workflows
    assert "workflow_dispatch" in trigger


def test_manual_deploy_still_resolves_successful_ci_by_workflow_file() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "actions/workflows/ci.yml/runs" in text
    assert 'row.get("event") == "push"' in text
    assert 'row.get("head_branch") == "main"' in text
    assert 'row.get("conclusion") == "success"' in text
    assert "/usr/local/sbin/hermes-deals-deploy-main" in text
