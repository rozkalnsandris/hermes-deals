from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-ownership-separator-rpi5-audit.yml"


def test_reporter_can_mutate_pull_request_metadata_without_broadening_rpi5_job() -> None:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    report_permissions = payload["jobs"]["report"]["permissions"]
    assert report_permissions == {
        "contents": "read",
        "issues": "write",
        "pull-requests": "write",
    }

    rpi5_permissions = payload["jobs"]["rpi5-audit"]["permissions"]
    assert rpi5_permissions == {}
