from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "tools" / "runner" / "run-hermes-deals-307-phase-d-owner-finalizer.sh"
TARGET_SHA = "b7a94a8a3d150db43ac051c59a304c31e901ef21"


def source() -> str:
    return FINALIZER.read_text(encoding="utf-8")


def test_phase_d_owner_finalizer_is_syntax_valid_and_pinned_to_merged_source() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(FINALIZER)], check=True)

    assert "FINALIZER_VERSION='hermes-deals-307-phase-d-owner-finalizer-v1'" in text
    assert "SOURCE_PR='366'" in text
    assert f"TARGET_SHA='{TARGET_SHA}'" in text
    assert "AUDIT_REPO='/home/andris/hermes-deals-audit-source-307'" in text
    assert "INSTALLER_REL='tools/runner/install-hermes-deals-307-phase-d-dispatch.sh'" in text
    assert "DISPATCHER='/usr/local/sbin/hermes-deals-307-phase-d-dispatch'" in text
    assert '[[ "$PR_MERGE_SHA" == "$TARGET_SHA" ]]' in text
    assert 'git_read "$AUDIT_REPO" merge-base --is-ancestor "$TARGET_SHA" origin/main' in text


def test_phase_d_owner_finalizer_materializes_dedicated_audit_clone_not_primary() -> None:
    text = source()

    assert 'git -C "$AUDIT_REPO" fetch --prune origin main' in text
    assert 'git -C "$AUDIT_REPO" switch --detach --discard-changes "$TARGET_SHA"' in text
    assert 'git -C "$PRIMARY" fetch' not in text
    assert 'git -C "$PRIMARY" switch' not in text
    assert 'git -C "$PRIMARY" checkout' not in text
    assert 'git -C "$PRIMARY" reset' not in text
    assert 'git -C "$PRIMARY" pull' not in text


def test_phase_d_owner_finalizer_bootstraps_trust_then_runs_read_only_preflight_only() -> None:
    text = source()

    installer = 'sudo bash "$INSTALLER" "$TARGET_SHA"'
    preflight = 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER" preflight'
    assert installer in text
    assert preflight in text
    assert text.index(installer) < text.index(preflight)

    assert '"$DISPATCHER" finalize-loopback' in text  # sudo authorization validation only
    assert '"$DISPATCHER" verify-loopback' in text  # sudo authorization validation only
    assert 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER" finalize-loopback' not in text
    assert 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER" verify-loopback' not in text
    assert 'sudo -u github-runner -- sudo --non-interactive "$DISPATCHER" rollback-dual' not in text
    assert "HERMES_DEALS_307_LOOPBACK_PREFLIGHT=PASS" in text
    assert "READ_ONLY_PHASE_D_PREFLIGHT=PASS" in text
    assert "NEXT_GITHUB_ACTION=/hermes-307 finalize-loopback" in text


def test_phase_d_owner_finalizer_requires_exact_three_runner_commands_and_no_rollback() -> None:
    text = source()

    assert 'grep -Fq "$DISPATCHER preflight"' in text
    assert 'grep -Fq "$DISPATCHER finalize-loopback"' in text
    assert 'grep -Fq "$DISPATCHER verify-loopback"' in text
    assert 'grep -Fq "$DISPATCHER rollback-dual"' in text
    assert "runner Phase D rollback-dual authorization is forbidden" in text
    assert "RUNNER_ROLLBACK_DUAL_AUTHORIZED=false" in text


def test_phase_d_owner_finalizer_proves_primary_env_and_runtime_unchanged() -> None:
    text = source()

    assert 'PRIMARY_ENV_STATE="$(file_state "$ENV_FILE")"' in text
    assert 'PRIMARY_WEB_ID="$(docker inspect "$WEB_NAME"' in text
    assert 'PRIMARY_API_ID="$(docker inspect "$API_NAME"' in text
    assert 'PRIMARY_DB_ID="$(docker inspect "$DB_NAME"' in text
    assert 'PRIMARY_CF_PID="$(systemctl show cloudflared.service -p MainPID --value)"' in text
    assert "production env changed during trust bootstrap" in text
    assert "web container changed during trust bootstrap" in text
    assert "api container changed during trust bootstrap" in text
    assert "database container changed during trust bootstrap" in text
    assert "cloudflared PID changed during trust bootstrap" in text
    assert "PRODUCTION_ENV_CHANGED=false" in text
    assert "PRODUCTION_RUNTIME_CHANGED=false" in text
    assert "WEB_CONTAINER_CHANGED=false" in text
    assert "API_CONTAINER_CHANGED=false" in text
    assert "DB_CONTAINER_CHANGED=false" in text
    assert "CLOUDFLARED_PID_CHANGED=false" in text


def test_phase_d_owner_finalizer_contains_no_phase_d_mutation_or_control_plane_write() -> None:
    text = source()

    for forbidden in (
        "api.cloudflare.com",
        "cloudflared tunnel",
        "systemctl restart",
        "systemctl stop",
        "systemctl start",
        "ufw allow",
        "ufw deny",
        "ufw delete",
        "docker compose up",
        "docker compose down",
        "alembic ",
        "psql ",
        "DEALS_BIND_IP=127.0.0.1",
    ):
        assert forbidden not in text

    assert "CLOUDFLARE_ROUTE_CHANGED=false" in text
    assert "UFW_CHANGED=false" in text
    assert "DATABASE_WRITE=false" in text
    assert "SHARED_CLOUDFLARED_LIFECYCLE=false" in text
