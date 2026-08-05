from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL = ROOT / ".agents/skills/hermes-deals-release/SKILL.md"
BUNDLE = ROOT / "config/hermes/hermes-deals-operator.yaml"
BUNDLE_INSTALLER = ROOT / "tools/install-hermes-deals-operator-bundle.sh"
RUNTIME_SYNC = (
    ROOT / "tools/runner/release/hermes-deals-release-runtime-sync"
)
RUNTIME_INSTALLER = ROOT / "tools/runner/install-hermes-deals-operator.sh"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_skill_requires_exact_owner_apply_and_full_verification() -> None:
    text = read(SKILL)
    for marker in (
        "bash tools/vscode-rpi5-release.sh check",
        "hermes-deals-release-runtime-sync <exact-40-sha>",
        "bash tools/vscode-rpi5-release.sh plan",
        "APPLY api-ui <40-sha>",
        "Never construct or infer the phrase on the owner’s behalf",
        "bash tools/vscode-rpi5-release.sh apply",
        "NO DEPLOY NEEDED",
        "https://deals.rozkalns.net/api/health",
        "https://deals.rozkalns.net/ui",
        "migration_commands_executed=false",
        "database_writes_authorized=false",
    ):
        assert marker in text

    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "docker compose up",
        "git reset",
        "git clean",
    ):
        assert f"no `{forbidden}`" in text or f"no {forbidden}" in text


def test_operator_bundle_loads_required_skills_and_safety_instruction() -> None:
    text = read(BUNDLE)
    for marker in (
        "name: hermes-deals-operator",
        "- github-auth",
        "- github-issues",
        "- github-pr-workflow",
        "- hermes-deals",
        "- hermes-deals-release",
        "APPLY api-ui <40-sha>",
        "database_writes_authorized=false",
    ):
        assert marker in text


def test_bundle_installer_is_user_scoped_and_non_production() -> None:
    subprocess.run(["bash", "-n", str(BUNDLE_INSTALLER)], check=True)
    text = read(BUNDLE_INSTALLER)
    for marker in (
        "run as the andris user, not root",
        "/home/andris/hermes-deals",
        "hermes bundles reload",
        "hermes bundles show hermes-deals-operator",
        "BUNDLE_INSTALL_RESULT=PASS",
        "PRODUCTION_CHANGED=false",
    ):
        assert marker in text
    assert "sudo " not in text
    assert "docker " not in text


def test_runtime_sync_is_exact_main_ci_gated_and_container_stable() -> None:
    subprocess.run(["bash", "-n", str(RUNTIME_SYNC)], check=True)
    text = read(RUNTIME_SYNC)
    for marker in (
        "[[ \"$#\" -eq 1 ]]",
        "requested SHA is not exact current origin/main",
        "exact current main has no successful CI push run",
        "release-control worktree is not clean",
        "checkout --quiet --detach \"$TARGET_SHA\"",
        "install-rpi5-release-dispatcher.sh",
        "production API container changed during runtime sync",
        "production database container changed during runtime sync",
        "hermes-deals-release-dispatch",
        "hermes-deals-release-register",
        "hermes-deals-release-bridge",
        "hermes-deals-release-auto-register",
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
