from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "tools" / "runner" / "release" / "hermes-deals-release-bridge"
AUTO_REGISTER = (
    ROOT / "tools" / "runner" / "release" / "hermes-deals-release-auto-register"
)
BOOTSTRAP = ROOT / "tools" / "runner" / "bootstrap-hermes-deals-release-runtime.sh"
RUNBOOK = ROOT / "docs" / "operations" / "hermes-deals-release-bridge.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_bridge_compiles_and_has_no_arbitrary_shell_execution() -> None:
    text = read(BRIDGE)
    compile(text, str(BRIDGE), "exec")
    assert "from app." not in text
    assert "import requests" not in text
    assert "subprocess.run(" in text
    assert "shell=True" not in text
    assert "eval(" not in text
    assert 'LOCK_PATH = Path("/run/lock/hermes-deals-release-bridge.lock")' in text
    assert "fcntl.LOCK_EX | fcntl.LOCK_NB" in text


def test_bridge_accepts_only_exact_owner_authored_requests() -> None:
    text = read(BRIDGE)
    for marker in (
        'REPOSITORY = "rozkalnsandris/hermes-deals"',
        'OWNER_LOGIN = "rozkalnsandris"',
        "OWNER_ID = 277435981",
        'REQUEST_MARKER = "<!-- hermes-deals-release-request-v1 -->"',
        'READY = "hermes:deploy-ready"',
        'RUNNING = "hermes:deploy-running"',
        'PASS = "hermes:deploy-pass"',
        'FAIL = "hermes:deploy-fail"',
        'BLOCKED = "hermes:deploy-blocked"',
        "set(request) != ALLOWED_FIELDS",
        'request.get("owner_authorized") is not True',
        'request.get("database_writes_authorized") is not False',
        'request["source_issue"] == 20',
        "release SHA must be exact lowercase 40-character hex",
        "source PR merge SHA does not match request",
        "request is stale because main has advanced",
    ):
        assert marker in text


def test_bridge_plans_before_apply_and_requires_sanitized_artifact() -> None:
    text = read(BRIDGE)
    for marker in (
        'dispatch(client, int(issue["number"]), request, "plan")',
        'state.get("phase") == "plan" and request.get("mode") == "apply"',
        'f"APPLY api-ui {request[\'release_sha\']}"',
        "workflow dispatch correlation became ambiguous",
        "successful workflow has no unique non-empty release artifact",
        "Hermes made no alternative attempt.",
        "close_issue(client, int(issue[\"number\"]))",
    ):
        assert marker in text
    assert "alembic upgrade" not in text
    assert "docker compose" not in text
    assert "docker run" not in text


def test_auto_register_parses_and_preserves_release_safety() -> None:
    subprocess.run(["bash", "-n", str(AUTO_REGISTER)], check=True)
    text = read(AUTO_REGISTER)
    for marker in (
        "auto-register must run as root",
        "release-control worktree is not clean",
        "release-control HEAD is not the requested SHA",
        "exact main SHA has no successful CI push run",
        "expected exactly one FastAPI version",
        "current production image tag is not release-bound",
        "rollback full SHA could not be resolved uniquely",
        'docker image save "$CURRENT_TAG" | gzip -n',
        '"$REGISTER" "${ARGS[@]}"',
        "DATABASE_WRITES_AUTHORIZED=false",
    ):
        assert marker in text
    assert "alembic upgrade" not in text
    assert "docker compose down" not in text
    assert 'git -C "$PRIMARY" checkout' not in text
    assert 'git -C "$PRIMARY" reset' not in text


def test_bootstrap_verifies_runner_digest_and_narrow_sudo() -> None:
    subprocess.run(["bash", "-n", str(BOOTSTRAP)], check=True)
    text = read(BOOTSTRAP)
    for marker in (
        "origin/main does not equal the authorized bootstrap SHA",
        "persistent bridge token is not owned by the allowlisted owner",
        "actions-runner-linux-arm64-",
        'digest.startswith("sha256:")',
        "GitHub Actions runner archive digest mismatch",
        '--name "$RUNNER_NAME"',
        '--labels "$RUNNER_LABEL"',
        "must not belong to docker group",
        'bash "$SOURCE/tools/runner/install-rpi5-release-dispatcher.sh"',
        "andris ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-release-bridge poll",
        "--no-agent",
        '--script "$(basename "$HERMES_SCRIPT")"',
        "HERMES_NO_AGENT=true",
        "DATABASE_WRITES_AUTHORIZED=false",
    ):
        assert marker in text
    sudoers = text.split("<<'SUDOERS'\n", 1)[1].split("\nSUDOERS\n", 1)[0]
    assert "NOPASSWD: ALL" not in sudoers
    assert "hermes-deals-release-auto-register" not in sudoers
    assert "hermes-deals-release-register" not in sudoers
    assert "docker" not in sudoers


def test_runbook_documents_no_agent_and_high_risk_blocks() -> None:
    text = read(RUNBOOK)
    for marker in (
        "Hermes no-agent cron polls every five minutes",
        "Normal polling makes no model call and uses no tokens",
        "Actions: read and write",
        "Issues: read and write",
        "<!-- hermes-deals-release-request-v1 -->",
        '"database_writes_authorized": false',
        "source PR must be squash-merged to `main`",
        "dispatches `plan`",
        "dispatches `apply`",
        "B15M2 issue #20 remains explicitly rejected",
        "database migration or production data write",
    ):
        assert marker in text
