from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools/vscode-rpi5-release.sh"
MAIN_REGISTER = ROOT / "tools/runner/release/hermes-deals-release-main-register"
MAIN_DEPLOY = ROOT / "tools/runner/release/hermes-deals-release-main-deploy"
RUNTIME_INSTALLER = ROOT / "tools/runner/install-rpi5-release-dispatcher.sh"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_launcher_supports_only_check_and_deploy() -> None:
    subprocess.run(["bash", "-n", str(LAUNCHER)], check=True)
    text = read(LAUNCHER)

    for marker in (
        'MODE="${1:-check}"',
        "exact current main has no successful CI push run",
        "cumulative Compose change detected",
        "live schema is not already at exact target Alembic head",
        'sudo --non-interactive "$RUNTIME_SYNC" "$REMOTE_SHA"',
        'sudo --non-interactive "$MAIN_DEPLOY" "$REMOTE_SHA"',
        "https://deals.rozkalns.net/api/health",
        "https://deals.rozkalns.net/ui",
        "DEPLOY PASS",
        "MIGRATION_COMMANDS_EXECUTED=false",
        "DATABASE_WRITES_AUTHORIZED=false",
        "ROLLBACK_PERFORMED=false",
        'usage: $0 {check|deploy}',
    ):
        assert marker in text

    for forbidden in (
        "gh issue create",
        "hermes:deploy-ready",
        "create_bridge_request",
        "plan)",
        "apply)",
        "APPLY api-ui",
    ):
        assert forbidden not in text


def test_main_register_uses_exact_main_and_ci_without_pr_or_issue() -> None:
    subprocess.run(["bash", "-n", str(MAIN_REGISTER)], check=True)
    text = read(MAIN_REGISTER)

    for marker in (
        "main register must run as root",
        "release SHA is not exact current main",
        "exact main SHA has no successful CI push run",
        "hermes-deals-release-register",
        "release-control worktree is not clean",
        "canonical rollback alias does not match the running image",
        "MAIN_REGISTER_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
    ):
        assert marker in text

    for forbidden in (
        "PR_NUMBER",
        "/pulls/",
        "source issue",
        "gh issue",
    ):
        assert forbidden not in text


def test_main_register_accepts_only_bounded_managed_baselines_with_oci_binding() -> None:
    text = read(MAIN_REGISTER)
    assert '^hermes-deals-api:(main|w4b|w4c)-([0-9a-f]{12})$' in text
    assert '^hermes-deals-api:release-[A-Za-z0-9_.-]+$' in text
    assert 'MANAGED_TAG_SHA="${BASH_REMATCH[2]}"' in text
    assert '[[ "$MANAGED_TAG_SHA" == "${CURRENT_REVISION:0:12}" ]]' in text
    assert "managed current production image requires an exact OCI revision label" in text
    assert "managed current production image tag does not match OCI revision" in text
    assert '[[ "$CURRENT_TAG" == hermes-deals-api:release-* ]]' not in text


def test_main_deploy_reuses_controlled_dispatcher_and_verifies_boundaries() -> None:
    subprocess.run(["bash", "-n", str(MAIN_DEPLOY)], check=True)
    text = read(MAIN_DEPLOY)

    for marker in (
        "main deploy must run as root through the narrow sudo rule",
        "hermes-deals-release-main-register",
        "hermes-deals-release-dispatch",
        "production API container changed during registration",
        "production database container changed during registration",
        "dispatcher produced no direct-deploy evidence",
        "production database container changed during API/UI deploy",
        "live Alembic revision changed during API/UI deploy",
        "MAIN_DEPLOY_RESULT=PASS",
        "MIGRATION_COMMANDS_EXECUTED=false",
        "DATABASE_WRITES_AUTHORIZED=false",
        "ROLLBACK_PERFORMED=false",
    ):
        assert marker in text

    assert "docker compose up" not in text
    assert "alembic upgrade" not in text
    assert "alembic downgrade" not in text
    assert "gh issue" not in text


def test_release_runtime_installer_installs_direct_main_helpers() -> None:
    subprocess.run(["bash", "-n", str(RUNTIME_INSTALLER)], check=True)
    text = read(RUNTIME_INSTALLER)

    for marker in (
        "SOURCE_MAIN_REGISTER",
        "SOURCE_MAIN_DEPLOY",
        "hermes-deals-release-main-register",
        "hermes-deals-release-main-deploy",
        "MAIN_REGISTER_SHA256",
        "MAIN_DEPLOY_SHA256",
        "release source index ownership changed during installation",
    ):
        assert marker in text

    assert "github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-main-deploy" not in text
