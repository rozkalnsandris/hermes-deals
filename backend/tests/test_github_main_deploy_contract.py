from __future__ import annotations

from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-main.yml"
HELPER = ROOT / "tools" / "runner" / "release" / "hermes-deals-deploy-main"
INSTALLER = ROOT / "tools" / "runner" / "install-github-main-deploy.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_is_manual_main_ci_then_self_hosted_deploy() -> None:
    text = read(WORKFLOW)
    data = yaml.safe_load(text)
    trigger = data.get("on") or data.get(True)

    assert set(trigger) == {"workflow_dispatch"}
    assert "Check exact main and CI" in text
    assert "actions/workflows/ci.yml/runs" in text
    assert 'run.get("event") == "push"' in text
    assert 'run.get("head_branch") == "main"' in text
    assert "workflow SHA is stale" in text
    assert "hermes-deals-release" in text
    assert "/usr/local/sbin/hermes-deals-deploy-main" in text
    assert "https://deals.rozkalns.net/api/health" in text
    assert "https://deals.rozkalns.net/ui" in text
    for forbidden in ("pr_number", "issue", "plan", "APPLY api-ui", "release registry"):
        assert forbidden not in text


def test_root_helper_is_exact_main_api_only_with_rollback() -> None:
    text = read(HELPER)
    subprocess.run(["bash", "-n", str(HELPER)], check=True)

    for marker in (
        "requested SHA is not exact current origin/main",
        "release-control worktree must remain detached",
        "docker build",
        "org.opencontainers.image.revision=$TARGET_SHA",
        "up -d --no-deps --no-build --wait api",
        "production database container changed",
        "production web container changed",
        "DEPLOY_RESULT=FAIL_ROLLBACK_PASS",
        "DEPLOY_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
        "MIGRATION_COMMANDS_EXECUTED=false",
        "ROLLBACK_PERFORMED=false",
    ):
        assert marker in text

    assert "alembic upgrade" not in text
    assert "docker compose down" not in text
    assert "workflow_dispatch" not in text
    assert "github issue" not in text.lower()


def test_installer_grants_only_new_helper_to_existing_runner() -> None:
    text = read(INSTALLER)
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    assert "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service" in text
    assert "github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-deploy-main *" in text
    assert "RUNNER_HAS_DOCKER_GROUP=false" in text
    assert "PRODUCTION_CHANGED=false" in text
