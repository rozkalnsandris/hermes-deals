from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "tools" / "runner" / "release" / "hermes-deals-release-bridge"
AUTO_REGISTER = (
    ROOT / "tools" / "runner" / "release" / "hermes-deals-release-auto-register"
)
DISPATCHER = ROOT / "tools" / "runner" / "release" / "hermes-deals-release-dispatch"
INSTALLER = ROOT / "tools" / "runner" / "install-rpi5-release-dispatcher.sh"
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


def test_dispatch_is_persisted_before_send_and_never_repeated_when_uncertain() -> None:
    text = read(BRIDGE)
    for marker in (
        "DISPATCH_RECOVERY_SECONDS = 600",
        '"schema_version": 2',
        '"run_id": None',
        '"previous_run_ids": previous',
        '"dispatched_at": dt.datetime.now(dt.timezone.utc).isoformat()',
        "save_state(state)",
        "def find_dispatched_run(",
        "def correlate_dispatch(",
        "GitHub dispatch outcome could not be correlated within the bounded recovery window.",
        "The bridge did not dispatch a replacement run.",
        "workflow correlation is pending and will not be dispatched again.",
    ):
        assert marker in text
    dispatch_body = text.split("def dispatch(", 1)[1].split("def verify_artifact(", 1)[0]
    assert dispatch_body.index("save_state(state)") < dispatch_body.index("client.post(")
    reconcile_body = text.split("def reconcile(", 1)[1].split("def block(", 1)[0]
    assert 'if run_raw is None:' in reconcile_body
    assert "correlate_dispatch(client, state, 0)" in reconcile_body
    assert reconcile_body.count("apply_id = dispatch(") == 1


def test_auto_register_normalizes_verified_legacy_rollback_image() -> None:
    subprocess.run(["bash", "-n", str(AUTO_REGISTER)], check=True)
    text = read(AUTO_REGISTER)
    for marker in (
        "auto-register must run as root",
        "release-control worktree is not clean",
        "release-control HEAD is not the requested SHA",
        "exact main SHA has no successful CI push run",
        "expected exactly one FastAPI version",
        "current production image is not a Hermes Deals release image",
        'org.opencontainers.image.revision',
        "current production image has malformed OCI revision label",
        'ROLLBACK_PROVENANCE=\'oci-revision\'',
        'ROLLBACK_TAG="hermes-deals-api:release-${ROLLBACK_VERSION}-${ROLLBACK_SHA:0:7}"',
        'docker image tag "$CURRENT_IMAGE_ID" "$ROLLBACK_TAG"',
        'docker image save "$ROLLBACK_TAG" | gzip -n',
        '"$REGISTER" "${ARGS[@]}"',
        "DATABASE_WRITES_AUTHORIZED=false",
    ):
        assert marker in text
    assert "alembic upgrade" not in text
    assert "docker compose down" not in text
    assert 'git -C "$PRIMARY" checkout' not in text
    assert 'git -C "$PRIMARY" reset' not in text


def test_dispatcher_reads_alembic_directly_and_preserves_schema() -> None:
    subprocess.run(["bash", "-n", str(DISPATCHER)], check=True)
    text = read(DISPATCHER)
    for marker in (
        "production OCI revision does not match registered rollback baseline",
        "read_live_alembic()",
        "SELECT version_num FROM alembic_version;",
        'PRE_ALEMBIC="$(read_live_alembic)"',
        'POST_ALEMBIC="$(read_live_alembic)"',
        'RESTORED_ALEMBIC="$(read_live_alembic)"',
        '"migration_commands_executed": False',
        '"database_writes_authorized": False',
    ):
        assert marker in text
    assert "alembic upgrade" not in text
    assert "alembic downgrade" not in text


def test_runtime_installer_updates_all_release_components_from_exact_main() -> None:
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    text = read(INSTALLER)
    for marker in (
        "installer source must be the isolated release-control worktree",
        "release source HEAD is not exact origin/main",
        'SOURCE_BRIDGE="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-bridge"',
        'SOURCE_AUTO_REGISTER="$SOURCE_WORKTREE/tools/runner/release/hermes-deals-release-auto-register"',
        'install -o root -g root -m 0755 "$SOURCE_BRIDGE" "$BRIDGE"',
        'install -o root -g root -m 0755 "$SOURCE_AUTO_REGISTER" "$AUTO_REGISTER"',
        "AUTO_REGISTER_SHA256",
        "DATABASE_WRITES_AUTHORIZED=false",
    ):
        assert marker in text


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
