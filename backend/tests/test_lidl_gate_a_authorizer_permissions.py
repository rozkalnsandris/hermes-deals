from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "lidl-weekly-gate-a-rpi5.yml"


def test_gate_a_authorizer_has_read_only_pull_request_api_permission() -> None:
    payload = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    permissions = payload.get("permissions")

    assert permissions == {
        "contents": "read",
        "pull-requests": "read",
    }


def test_gate_a_authorizer_permission_remains_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    top_level = text.split("concurrency:", maxsplit=1)[0]

    assert "contents: write" not in top_level
    assert "pull-requests: read" in top_level
    assert "pull-requests: write" not in top_level
    assert "issues: write" not in top_level
    assert "actions: write" not in top_level
