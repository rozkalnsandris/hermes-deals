from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents/skills/hermes-deals-release/SKILL.md"
BUNDLE = ROOT / "config/hermes/hermes-deals-operator.yaml"
BUNDLE_INSTALLER = ROOT / "tools/install-hermes-deals-operator-bundle.sh"
RUNTIME_SYNC = ROOT / "tools/runner/release/hermes-deals-release-runtime-sync"
RUNTIME_INSTALLER = ROOT / "tools/runner/install-hermes-deals-operator.sh"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_skill_preserves_high_risk_prohibitions() -> None:
    text = read(SKILL)
    for marker in (
        "bash tools/vscode-rpi5-release.sh check",
        "NO DEPLOY NEEDED",
        "https://deals.rozkalns.net/api/health",
        "https://deals.rozkalns.net/ui",
        "database_writes_authorized=false",
    ):
        assert marker in text
    for forbidden in ("alembic upgrade", "alembic downgrade", "docker compose up", "git reset", "git clean"):
        assert f"no `{forbidden}`" in text or f"no {forbidden}" in text


def test_operator_bundle_is_deploy_only_without_github_editing_skills() -> None:
    text = read(BUNDLE)
    for marker in (
        "name: hermes-deals-operator",
        "- hermes-deals-release",
        "only `check` or `deploy`",
        "DEPLOY api-ui <40-sha>",
        "database_writes_authorized=false",
        "do not create or edit issues, branches, commits, pushes, pull requests, reviews, merges",
    ):
        assert marker in text
    for forbidden in ("github-auth", "github-issues", "github-pr-workflow", "- hermes-deals\n"):
        assert forbidden not in text


def test_bundle_installer_is_user_scoped_and_non_production() -> None:
    subprocess.run(["bash", "-n", str(BUNDLE_INSTALLER)], check=True)
    text = read(BUNDLE_INSTALLER)
    for marker in (
        "run as the andris user, not root",
        "/home/andris/hermes-deals",
        "hermes bundles reload",
        "hermes bundles show hermes-deals-operator",
        'SKILLS_OUTPUT="$(hermes skills list)"',
        'grep -Fq -- "$skill" <<<"$SKILLS_OUTPUT"',
        "BUNDLE_INSTALL_RESULT=PASS",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text
    assert 'hermes skills list | grep -Fq' not in text
    assert "sudo " not in text
    assert "docker " not in text


def test_runtime_sync_is_exact_main_ci_gated_and_container_stable() -> None:
    subprocess.run(["bash", "-n", str(RUNTIME_SYNC)], check=True)
    text = read(RUNTIME_SYNC)
    for marker in (
        "requested SHA is not exact current origin/main",
        "exact current main has no successful CI push run",
        "release-control worktree is not clean",
        "production API container changed during runtime sync",
        "production database container changed during runtime sync",
        "RUNTIME_SYNC_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text
    for forbidden in ("alembic upgrade", "alembic downgrade", "docker compose up", "git reset", "git clean", "rm -rf"):
        assert forbidden not in text


def test_runtime_installer_grants_only_named_sync_helper() -> None:
    subprocess.run(["bash", "-n", str(RUNTIME_INSTALLER)], check=True)
    text = read(RUNTIME_INSTALLER)
    for marker in (
        "installer source must be the isolated release-control worktree",
        "release-control HEAD is not exact origin/main",
        "/usr/local/sbin/hermes-deals-release-runtime-sync *",
        "visudo -cf",
        "OPERATOR_RUNTIME_INSTALL_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text
    assert "NOPASSWD: ALL" not in text
    assert "/bin/bash *" not in text
    assert "/bin/sh *" not in text
