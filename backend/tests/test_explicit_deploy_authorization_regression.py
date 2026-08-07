from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-main.yml"


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


def test_manual_deploy_requires_owner_main_ref_exact_sha_and_confirmation() -> None:
    text = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    deploy = yaml.safe_load(text)
    inputs = _workflow_trigger(deploy)["workflow_dispatch"]["inputs"]

    assert inputs["target_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True
    assert "ORIGINAL_ACTOR: ${{ github.actor }}" in text
    assert "TRIGGERING_ACTOR: ${{ github.triggering_actor }}" in text
    assert 'os.environ["EVENT_REF"] != "refs/heads/main"' in text
    assert "deploy-main.yml@refs/heads/main" in text
    assert 'confirmation != f"DEPLOY {target_sha}"' in text
    assert "actions/workflows/ci.yml/runs" in text
    assert 'row.get("event") == "push"' in text
    assert 'row.get("head_branch") == "main"' in text
    assert 'row.get("head_sha") == target_sha' in text
    assert 'row.get("conclusion") == "success"' in text
    assert "/usr/local/sbin/hermes-deals-deploy-main" in text
