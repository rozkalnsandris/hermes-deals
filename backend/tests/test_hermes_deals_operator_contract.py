from __future__ import annotations

import json
import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents/skills/hermes-deals-release/SKILL.md"
BUNDLE = ROOT / "config/hermes/hermes-deals-operator.yaml"
BUNDLE_INSTALLER = ROOT / "tools/install-hermes-deals-operator-bundle.sh"
RUNTIME_SYNC = ROOT / "tools/runner/release/hermes-deals-release-runtime-sync"
RUNTIME_INSTALLER = ROOT / "tools/runner/install-hermes-deals-operator.sh"
TASKS = ROOT / ".vscode/tasks.json"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_skill_is_deploy_only_check_then_deploy() -> None:
    text = read(SKILL)
    for marker in (
        "This skill is only a deploy operator.",
        "bash tools/vscode-rpi5-release.sh check",
        "bash tools/vscode-rpi5-release.sh deploy",
        "Do not run a separate Plan.",
        "Do not create a deploy issue.",
        "DEPLOY PASS",
        "PUBLIC_API_HEALTH=PASS",
        "PUBLIC_UI=PASS",
        "migration_commands_executed=false",
        "database_writes_authorized=false",
        "Never retry automatically.",
    ):
        assert marker in text

    for forbidden in (
        "APPLY api-ui <40-sha>",
        "bash tools/vscode-rpi5-release.sh plan",
        "bash tools/vscode-rpi5-release.sh apply",
    ):
        assert forbidden not in text

    for forbidden_action in (
        "edit any file",
        "create or modify an issue",
        "create a commit or push",
        "create, review, update or merge a pull request",
    ):
        assert forbidden_action in text


def test_operator_bundle_has_no_issue_or_pr_workflow_skill() -> None:
    text = read(BUNDLE)
    for marker in (
        "name: hermes-deals-operator",
        "- github-auth",
        "- hermes-deals",
        "- hermes-deals-release",
        "only a deploy operator",
        "Never run Plan",
        "database_writes_authorized=false",
    ):
        assert marker in text

    for forbidden in (
        "- github-issues",
        "- github-pr-workflow",
        "APPLY api-ui",
    ):
        assert forbidden not in text


def test_bundle_installer_is_user_scoped_and_deploy_only() -> None:
    subprocess.run(["bash", "-n", str(BUNDLE_INSTALLER)], check=True)
    text = read(BUNDLE_INSTALLER)
    for marker in (
        "run as the andris user, not root",
        "/home/andris/hermes-deals",
        "hermes bundles reload",
        "hermes bundles show hermes-deals-operator",
        'SKILLS_OUTPUT="$(hermes skills list)"',
        "for skill in github-auth hermes-deals hermes-deals-release",
        "BUNDLE_INSTALL_RESULT=PASS",
        "OPERATOR_ROLE=deploy-only",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text
    assert "github-issues" not in text
    assert "github-pr-workflow" not in text
    assert "sudo " not in text
    assert "docker " not in text


def test_runtime_sync_installs_direct_main_components_without_production_change() -> None:
    subprocess.run(["bash", "-n", str(RUNTIME_SYNC)], check=True)
    text = read(RUNTIME_SYNC)
    for marker in (
        '[[ "$#" -eq 1 ]]',
        "requested SHA is not exact current origin/main",
        "exact current main has no successful CI push run",
        "release-control worktree is not clean",
        'checkout --quiet --detach "$TARGET_SHA"',
        "install-rpi5-release-dispatcher.sh",
        "production API container changed during runtime sync",
        "production database container changed during runtime sync",
        "hermes-deals-release-main-register",
        "hermes-deals-release-main-deploy",
        "DIRECT_MAIN_DEPLOY_READY=true",
        "RUNTIME_SYNC_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text

    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "docker compose up",
        "git reset",
        "git clean",
        "rm -rf",
    ):
        assert forbidden not in text


def test_runtime_installer_grants_only_sync_and_direct_main_deploy() -> None:
    subprocess.run(["bash", "-n", str(RUNTIME_INSTALLER)], check=True)
    text = read(RUNTIME_INSTALLER)
    for marker in (
        "installer source must be the isolated release-control worktree",
        "release-control HEAD is not exact origin/main",
        "/usr/local/sbin/hermes-deals-release-runtime-sync *",
        "/usr/local/sbin/hermes-deals-release-main-deploy *",
        "DIRECT_MAIN_DEPLOY_AUTHORIZED=true",
        "visudo -cf",
        "OPERATOR_RUNTIME_INSTALL_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text

    assert "NOPASSWD: ALL" not in text
    assert "/bin/bash *" not in text
    assert "/bin/sh *" not in text


def test_vscode_tasks_are_only_check_and_deploy() -> None:
    data = json.loads(read(TASKS))
    labels = [task["label"] for task in data["tasks"]]
    args = [task["args"][-1] for task in data["tasks"]]
    assert labels == [
        "Hermes Deals: Check deploy",
        "Hermes Deals: Deploy current main",
    ]
    assert args == ["check", "deploy"]
