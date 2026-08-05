from __future__ import annotations

from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "rpi5-release-command.yml"
INSTALLER = ROOT / "tools" / "runner" / "install-rpi5-release-dispatcher.sh"
RUNBOOK = ROOT / "docs" / "operations" / "rpi5-github-release-runner.md"
DISPATCHER = ROOT / "tools" / "runner" / "release" / "hermes-deals-release-dispatch"
REGISTER = ROOT / "tools" / "runner" / "release" / "hermes-deals-release-register"
AUDIT_WORKFLOW = ROOT / ".github" / "workflows" / "rpi5-audit-command.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_workflow_is_manual_owner_only_and_current_main_only() -> None:
    text = read(WORKFLOW)
    data = yaml.safe_load(text)
    trigger = data.get("on") or data.get(True)

    assert set(trigger) == {"workflow_dispatch"}
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert 'if current_main_sha != release_sha:' in text
    assert "release SHA is stale; only exact current main can be released" in text
    assert 'pr.get("merge_commit_sha") != release_sha' in text
    assert "workflow_dispatch actor numeric identity is not allowlisted" in text


def test_release_requires_exact_sha_ci_and_optional_audit_binding() -> None:
    text = read(WORKFLOW)

    for marker in (
        "actions/workflows/ci.yml/runs",
        'run.get("event") == "push"',
        'run.get("head_sha") == release_sha',
        'run.get("conclusion") == "success"',
        "RPi5 approved audit command",
        "Netto shadow RPi5 audit",
        'audit.get("head_sha") != release_sha',
        'expected_phrase = f"APPLY api-ui {release_sha}"',
    ):
        assert marker in text


def test_release_serializes_general_audit_and_rechecks_dedicated_netto_audit() -> None:
    release = read(WORKFLOW)
    audit = read(AUDIT_WORKFLOW)
    installer = read(INSTALLER)

    assert "group: hermes-deals-rpi5-audit" in release
    assert "group: hermes-deals-rpi5-audit" in audit
    assert "netto-shadow-rpi5-audit.yml/runs?status=" in release
    assert "dedicated Netto RPi5 audit is active; release refused" in release
    assert "dedicated Netto RPi5 audit became active; release refused" in release
    assert "main advanced after authorization; release refused" in release
    assert "hermes-deals-release" in release
    release_job = release.split("\n  release:\n", 1)[1].split("\n  report:\n", 1)[0]
    assert "hermes-deals-audit" not in release_job
    assert "github-release-runner" in installer
    assert "github-runner ALL=" not in installer
    assert (
        "github-release-runner ALL=(root) NOPASSWD: "
        "/usr/local/sbin/hermes-deals-release-dispatch"
    ) in installer
    assert "github-release-runner must not belong to docker group" in installer


def test_self_hosted_release_job_never_checks_out_repository_code() -> None:
    text = read(WORKFLOW)
    release_job = text.split("\n  release:\n", 1)[1].split("\n  report:\n", 1)[0]

    assert "actions/checkout" not in release_job
    assert "/usr/local/sbin/hermes-deals-release-dispatch" in release_job
    assert "inputs.authorization" not in release_job
    assert "needs.authorize.outputs.authorization" not in release_job
    assert "upload-artifact@v4" in release_job
    assert 'artifact_dir=$export_dir/release-evidence' in release_job
    assert "runner-dispatch.log" not in release_job
    assert "runner-request.txt" not in release_job
    assert "if-no-files-found: warn" in release_job


def test_dispatcher_is_api_only_fail_closed_and_has_rollback() -> None:
    dispatch = read(DISPATCHER)

    for marker in (
        '[[ "$RELEASE_CLASS" =~ ^(smoke|api-ui)$ ]]',
        '[[ "$RELEASE_CLASS" != smoke || "$MODE" == plan ]]',
        "/run/lock/hermes-deals-rpi5-privileged.lock",
        "an existing Hermes Deals audit dispatcher is active",
        "release is not root-registered for exact SHA",
        "production repo HEAD is not exact release SHA",
        "production image ID does not match registered rollback baseline",
        'docker image load --input "$ROLLBACK_ARCHIVE"',
        'docker image load --input "$IMAGE_ARCHIVE"',
        "up -d --no-deps --no-build --wait api",
        '"$POST_ALEMBIC" == "$PRE_ALEMBIC"',
        '"$RESTORED_ALEMBIC" == "$PRE_ALEMBIC"',
        "apply-failed-rollback-succeeded",
        '"database_writes_authorized": False',
        '"migration_commands_executed": False',
    ):
        assert marker in dispatch

    assert "alembic upgrade" not in dispatch
    assert "docker compose down" not in dispatch
    assert "git checkout" not in dispatch
    assert "git switch" not in dispatch


def test_root_registration_builds_tests_archives_and_restore_tests_exact_main() -> None:
    register = read(REGISTER)

    for marker in (
        "register tool must run as root",
        "registration source branch must be main",
        "registration source HEAD mismatch",
        "registration source worktree is not clean",
        '[[ -f "$ROLLBACK_ARCHIVE_SOURCE" && ! -L "$ROLLBACK_ARCHIVE_SOURCE" ]]',
        "org.opencontainers.image.revision=$NEW_SHA",
        "docker run --rm",
        "python -m pytest -q",
        "docker image save",
        "required CI run ID is invalid",
        "/run/lock/hermes-deals-rpi5-privileged.lock",
        "an existing Hermes Deals audit dispatcher is active",
        '"required_ci_run_id": int(required_ci_run_id)',
        "gzip -n",
        'docker image load --input "$ROLLBACK_ARCHIVE"',
        "ROLLBACK_RESTORE_TESTED=true",
        "REQUIRED_CI_RUN_ID=",
        "DATABASE_WRITES_AUTHORIZED=false",
        "PRODUCTION_APPLY_PERFORMED=false",
    ):
        assert marker in register


def test_release_installer_shell_syntax_and_sudo_scope() -> None:
    for path in (INSTALLER, DISPATCHER, REGISTER):
        result = subprocess.run(
            ["bash", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"

    text = read(INSTALLER)
    assert text.count("NOPASSWD:") == 1
    assert "github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-dispatch" in text
    sudoers_source = text.split("<<'SUDOERS'\n", 1)[1].split("\nSUDOERS\n", 1)[0]
    assert "hermes-deals-release-register" not in sudoers_source
    assert "tools/runner/release/hermes-deals-release-dispatch" in text
    assert "tools/runner/release/hermes-deals-release-register" in text
    for command in ("docker", "flock", "pgrep", "python3", "sudo", "tar", "visudo"):
        assert command in text


def test_runbook_keeps_install_apply_and_db_write_as_separate_authorizations() -> None:
    text = read(RUNBOOK)

    for marker in (
        "does not install the runner, register an image, deploy",
        "Migration and data-write releases are intentionally not included",
        "APPLY api-ui <40-character-sha>",
        "ROLLBACK_RESTORE_TESTED=true",
        "database_writes_authorized=false",
        "migration_commands_executed=false",
    ):
        assert marker in text
