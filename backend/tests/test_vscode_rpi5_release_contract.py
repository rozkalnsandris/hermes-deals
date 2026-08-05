from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_vscode_tasks_expose_check_plan_and_apply() -> None:
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = {task["label"] for task in tasks["tasks"]}
    assert labels == {
        "Hermes Deals: Check deploy",
        "Hermes Deals: Plan production deploy",
        "Hermes Deals: Apply production deploy",
    }

    modes = {
        tuple(task["args"])
        for task in tasks["tasks"]
    }
    assert modes == {
        ("tools/vscode-rpi5-release.sh", "check"),
        ("tools/vscode-rpi5-release.sh", "plan"),
        ("tools/vscode-rpi5-release.sh", "apply"),
    }


def test_release_launcher_preserves_fail_closed_boundaries() -> None:
    text = (ROOT / "tools" / "vscode-rpi5-release.sh").read_text(encoding="utf-8")
    required = (
        '[[ "$BRANCH" == "main" ]]',
        "git status --porcelain",
        '[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]',
        "current main SHA is not bound to exactly one merged PR",
        "database migration detected",
        "APPLY api-ui ${REMOTE_SHA}",
        "gh run watch",
        "rpi5-release-command.yml",
    )
    for marker in required:
        assert marker in text


def test_check_mode_has_no_release_dispatch() -> None:
    text = (ROOT / "tools" / "vscode-rpi5-release.sh").read_text(encoding="utf-8")
    check_block = text.split("  check)", 1)[1].split("  plan)", 1)[0]
    assert "gh workflow run" not in check_block
    assert "No production change was made" in check_block
