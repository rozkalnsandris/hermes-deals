from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/netto-weekly-transition-state.yml"
POLICY = REPO_ROOT / "config/retailer-weekly-schedule-policy-v1.json"


def test_netto_genuine_transition_uses_canonical_sunday_0010_schedule() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["timezone"] == "Europe/Berlin"
    assert policy["retailers"]["netto_5659"]["activation_default"] == (
        "Sun *-*-* 00:10:00 Europe/Berlin"
    )
    assert "    - cron: '10 0 * * 0'\n      timezone: 'Europe/Berlin'\n" in workflow
    assert "    - cron: '17 6 * * *'" not in workflow


def test_netto_genuine_transition_keeps_schedule_and_manual_canary_separate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "  schedule:\n" in workflow
    assert "  workflow_dispatch:\n" in workflow
    assert "[[ \"$EVENT_NAME\" == schedule ]] || exit 0" in workflow
    assert "prefix=os.environ['STATE_PREFIX'] if os.environ['EVENT_NAME']=='schedule' else os.environ['CANARY_PREFIX']" in workflow
    assert "run.get('event') == 'schedule'" in workflow
