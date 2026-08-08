from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "release" / "hermes-deals-307-loopback-finalize"


def source() -> str:
    return OPERATOR.read_text(encoding="utf-8")


def test_phase_d_operator_is_syntax_valid_and_has_exact_modes() -> None:
    text = source()
    subprocess.run(["bash", "-n", str(OPERATOR)], check=True)

    assert "hermes-deals-307-loopback-finalize <preflight|finalize-loopback|verify-loopback|rollback-dual>" in text
    assert '^(preflight|finalize-loopback|verify-loopback|rollback-dual)$' in text
    assert "LAN_IP='192.168.0.180'" in text
    assert "LOOPBACK_IP='127.0.0.1'" in text
    assert "PORT='9128'" in text


def test_phase_d_preflight_requires_existing_verified_dual_state() -> None:
    text = source()
    preflight = text.index("  preflight)")
    finalize = text.index("  finalize-loopback)")
    block = text[preflight:finalize]

    assert "verify_dual_runtime" in block
    assert "HERMES_DEALS_307_LOOPBACK_PREFLIGHT=PASS" in block
    assert "stale Phase D transition state exists" in block
    assert "up -d" not in block
    assert "rewrite_env_loopback" not in block


def test_phase_d_env_rewrite_is_exact_and_private() -> None:
    text = source()

    assert 'unset COMPOSE_ENV_FILES COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME DEALS_BIND_IP DEALS_HTTP_PORT DOCKER_CONTEXT DOCKER_HOST' in text
    assert 'install -o root -g root -m 0600 "$ENV_FILE" "$ENV_BACKUP"' in text
    assert 'chmod 0600 "$PHASE_D_STATE"' in text
    assert 'line.startswith(b"DEALS_BIND_IP=")' in text
    assert "if len(matches) != 1:" in text
    assert 'if body != b"DEALS_BIND_IP=" + old:' in text
    assert 'lines[idx] = b"DEALS_BIND_IP=" + new + ending' in text
    assert "os.fsync(handle.fileno())" in text
    assert "ENV_SHA256=" in text
    assert "production env restore SHA256 mismatch" in text


def test_finalize_recreates_only_web_and_arms_dual_rollback_before_mutation() -> None:
    text = source()
    start = text.index("  finalize-loopback)")
    end = text.index("  verify-loopback)")
    block = text[start:end]

    trap_pos = block.index("trap on_error ERR")
    rewrite_pos = block.index("rewrite_env_loopback")
    compose_pos = block.index('"${COMPOSE[@]}" up -d --no-deps --no-build --pull never web')
    verify_pos = block.index("verify_loopback_runtime")
    assert trap_pos < rewrite_pos < compose_pos < verify_pos

    assert "rollback_to_dual_internal" in block
    assert "DIRECT_LAN_9128_CLOSED=true" in block
    assert "ROLLBACK_TO_DUAL_AVAILABLE=true" in block
    assert "HERMES_DEALS_307_LOOPBACK_FINALIZE=PASS" in block
    assert " up -d --no-deps --no-build --pull never api" not in block
    assert " up -d --no-deps --no-build --pull never db" not in block


def test_automatic_failure_recovery_returns_to_dual_not_lan_only() -> None:
    text = source()
    start = text.index("rollback_to_dual_internal()")
    end = text.index('case "$MODE" in')
    block = text[start:end]

    assert "( restore_env_backup )" in block
    assert "( assert_compose_model dual )" in block
    assert '( "${DUAL_COMPOSE[@]}" up -d --no-deps --no-build --pull never web )' in block
    assert "( verify_dual_runtime )" in block
    assert "AUTO_ROLLBACK_TO_DUAL=PASS" in block
    assert "AUTO_ROLLBACK_TO_LAN" not in block


def test_loopback_verifier_requires_direct_lan_failure_and_preserves_identity() -> None:
    text = source()
    start = text.index("verify_loopback_runtime()")
    end = text.index("capture_phase_d_state()")
    block = text[start:end]

    assert '[[ "$(read_bind_ip)" == "$LOOPBACK_IP" ]]' in block
    assert "assert_compose_model loopback" in block
    assert "assert_bindings loopback" in block
    assert "assert_loopback_health" in block
    assert "assert_lan_closed" in block
    assert "verify_identity_from_phase_c" in block


def test_manual_rollback_to_dual_is_guarded_and_never_runner_default() -> None:
    text = source()
    start = text.index("  rollback-dual)")
    block = text[start:]

    assert "DEALS_307_ROLLBACK_DUAL_CONFIRMED" in block
    assert "verify_loopback_runtime" in block
    assert "restore_env_backup" in block
    assert "assert_compose_model dual" in block
    assert '"${DUAL_COMPOSE[@]}" up -d --no-deps --no-build --pull never web' in block
    assert "HERMES_DEALS_307_LOOPBACK_ROLLBACK_TO_DUAL=PASS" in block


def test_phase_d_operator_contains_no_shared_control_plane_or_db_mutation() -> None:
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
        "iptables ",
        "nft ",
        "alembic ",
        "psql ",
        "DROP TABLE",
        "UPDATE offer_",
        "docker compose down",
        "docker compose build",
        "docker compose pull",
    ):
        assert forbidden not in text

    assert text.count(" up -d --no-deps --no-build --pull never web") == 3
