"""Source guard against the two superseded pre-SIMPLE-DEPLOY release paths.

A successful production cutover is not permission to revive these paths.
Keep their historical workflow source for audit, but no job can execute.
"""
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML 1.1 may treat the 'on' key as boolean True.
    return workflow.get("on") or workflow.get(True) or {}


def test_legacy_manual_and_control_dispatch_cannot_reach_a_runner() -> None:
    workflow = _load("deploy-main.yml")

    # Preserve the original exact-SHA authorization and historical audit
    # contract, but block BOTH the authorizer and the privileged release job.
    assert set(_triggers(workflow)) == {"workflow_dispatch"}
    assert workflow["jobs"]["authorize"]["if"] == "${{ false }}"
    assert workflow["jobs"]["deploy"]["if"] == "${{ false }}"
    assert workflow["jobs"]["deploy"]["needs"] == "authorize"


def test_legacy_owner_issue_comment_cannot_dispatch_deploy_main() -> None:
    workflow = _load("hermes-direct-main-deploy.yml")
    trigger = _triggers(workflow)

    assert set(trigger) == {"issue_comment"}
    assert trigger["issue_comment"]["types"] == ["created"]
    job = workflow["jobs"]["authorize-and-dispatch"]
    condition = " ".join(str(job["if"]).split())
    assert condition.startswith("false && ")
    assert "github.event.issue.number == 553" in condition
    assert "startsWith(github.event.comment.body, '/hermes-deploy ')" in condition
    assert "github.event.issue.pull_request == null" in condition


def test_simple_deploy_caller_remains_active_on_main() -> None:
    workflow = _load("simple-deploy.yml")
    assert _triggers(workflow) == {"push": {"branches": ["main"]}}
    assert "uses" in workflow["jobs"]["deploy"]
    assert "rozkalnsandris/ops-workflows/.github/workflows/simple-deploy.yml@" in (
        workflow["jobs"]["deploy"]["uses"]
    )
