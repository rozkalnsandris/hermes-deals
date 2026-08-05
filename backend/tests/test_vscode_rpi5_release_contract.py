from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools" / "vscode-rpi5-release.sh"


def test_vscode_tasks_expose_only_check_and_deploy() -> None:
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    labels = {task["label"] for task in tasks["tasks"]}
    assert labels == {
        "Hermes Deals: Check deploy",
        "Hermes Deals: Deploy current main",
    }
    modes = {tuple(task["args"]) for task in tasks["tasks"]}
    assert modes == {
        ("tools/vscode-rpi5-release.sh", "check"),
        ("tools/vscode-rpi5-release.sh", "deploy"),
    }


def test_direct_launcher_has_only_check_and_deploy_modes() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "usage: tools/vscode-rpi5-release.sh {check|deploy}" in text
    assert "  plan)" not in text
    assert "  apply)" not in text
    assert "gh issue create" not in text
    assert "hermes:deploy-ready" not in text
    assert "hermes-deals-release-bridge poll" not in text
    assert "gh workflow run" not in text


def test_launcher_preserves_exact_main_and_ci_gates() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    for marker in (
        "PRIMARY_ROOT='/home/andris/hermes-deals'",
        '[[ "$(git branch --show-current)" == main ]]',
        "git status --porcelain",
        '[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]]',
        "current main SHA is not bound to exactly one merged PR",
        "exact current main has no successful CI push run",
        "production API image has no valid release SHA provenance",
        'git diff --name-only "${PRODUCTION_SHA}..${REMOTE_SHA}"',
        "cumulative Compose change detected",
        "cumulative migration change is not an added Alembic revision",
        "live schema is not already at exact target head",
    ):
        assert marker in text


def test_deploy_runs_only_guarded_root_components() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    for marker in (
        "DEPLOY api-ui ${REMOTE_SHA}",
        'sudo --non-interactive "$RUNTIME_SYNC" "$REMOTE_SHA"',
        'sudo --non-interactive "$AUTO_REGISTER" "$REMOTE_SHA" "$PR_NUMBER"',
        'sudo --non-interactive "$DISPATCH" api-ui "$REMOTE_SHA" apply',
        "PUBLIC_ORIGIN='https://deals.rozkalns.net'",
        'curl -fsS --max-time 20 "$PUBLIC_ORIGIN/api/health"',
        'curl -fsSI --max-time 20 "$PUBLIC_ORIGIN/ui"',
        "deployed runtime SHA does not equal exact current main",
        "DATABASE_WRITES_AUTHORIZED=false",
        "MIGRATION_COMMANDS_EXECUTED=false",
    ):
        assert marker in text
    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "docker compose up",
        "docker compose down",
        "git reset",
        "git clean",
    ):
        assert forbidden not in text


def test_check_mode_cannot_invoke_release_components() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    check_exit = '[[ "$MODE" == check ]] && exit 0'
    assert check_exit in text
    before_exit, after_exit = text.split(check_exit, 1)
    assert 'sudo --non-interactive "$RUNTIME_SYNC"' not in before_exit
    assert 'sudo --non-interactive "$AUTO_REGISTER"' not in before_exit
    assert 'sudo --non-interactive "$DISPATCH"' not in before_exit
    assert 'sudo --non-interactive "$RUNTIME_SYNC"' in after_exit
