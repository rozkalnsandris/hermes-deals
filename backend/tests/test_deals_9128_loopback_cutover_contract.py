from __future__ import annotations

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools/runner/release/hermes-deals-web-dual-bind-cutover"
RUNBOOK = ROOT / "docs/operations/DEALS_9128_LOOPBACK_CUTOVER.md"
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE = ROOT / "docker-compose.yml"


def test_operator_is_valid_shell_and_has_only_bounded_modes() -> None:
    subprocess.run(["bash", "-n", str(OPERATOR)], check=True)
    source = OPERATOR.read_text(encoding="utf-8")

    assert (
        "usage: hermes-deals-web-dual-bind-cutover "
        "<check|apply-dual|verify-dual|rollback-lan>"
    ) in source
    assert "^(check|apply-dual|verify-dual|rollback-lan)$" in source
    assert "STATE_DIR='/var/lib/hermes-deals-ops/issue-307'" in source
    assert "OVERRIDE_FILE=\"$STATE_DIR/dual-bind.compose.yml\"" in source
    assert "docker compose" in source
    assert "config --format json" in source


def test_transition_never_uses_wildcard_and_requires_exact_dual_bind_model() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    assert 'LAN_IP=\'192.168.0.180\'' in source
    assert 'LOOPBACK_IP=\'127.0.0.1\'' in source
    assert 'PORT=\'9128\'' in source
    assert '- "127.0.0.1:9128:80"' in source
    assert "('192.168.0.180', '9128', 80, 'tcp')" in source
    assert "('127.0.0.1', '9128', 80, 'tcp')" in source
    assert "if actual != expected:" in source
    assert "0.0.0.0:9128" not in source
    assert "[::]:9128" not in source


def test_operator_recreates_only_web_without_build_pull_or_dependencies() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    apply_lines = [
        line.strip()
        for line in source.splitlines()
        if ']}' in line and " up -d " in line
    ]
    assert apply_lines
    assert all("--no-deps --no-build --pull never web" in line for line in apply_lines)

    for forbidden in (
        "docker compose down",
        "docker rm ",
        "docker image rm",
        "docker image prune",
        "docker system prune",
        "docker pull",
        " up -d api",
        " up -d db",
        "alembic ",
        "psql ",
    ):
        assert forbidden not in source


def test_operator_keeps_shared_ingress_and_firewall_read_only() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    assert "systemctl is-active cloudflared.service" in source
    assert "systemctl show cloudflared.service -p MainPID --value" in source
    assert "cloudflared_tunnel_ha_connections" in source
    assert "ufw status numbered" in source

    for forbidden in (
        "systemctl start cloudflared",
        "systemctl stop cloudflared",
        "systemctl restart cloudflared",
        "systemctl enable cloudflared",
        "systemctl disable cloudflared",
        "ufw allow",
        "ufw deny",
        "ufw delete",
        "tunnel token",
        "--token",
    ):
        assert forbidden not in source


def test_dual_apply_preserves_api_db_image_and_cloudflared_identity() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    for marker in (
        "PRE_WEB_IMAGE",
        "PRE_API_ID",
        "PRE_DB_ID",
        "PRE_CF_PID",
        "api container changed during web cutover",
        "database container changed during web cutover",
        "web image changed during dual-bind cutover",
        "cloudflared PID changed during web cutover",
        "AUTO_ROLLBACK_TO_LAN=PASS",
        "HERMES_DEALS_307_DUAL_BIND_APPLY=PASS",
        "HERMES_DEALS_307_DUAL_BIND_VERIFY=PASS",
    ):
        assert marker in source


def test_manual_lan_rollback_is_explicitly_route_gated() -> None:
    source = OPERATOR.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "DEALS_307_ROUTE_LAN_CONFIRMED" in source
    assert "DEALS_307_ROUTE_LAN_CONFIRMED=yes" in runbook
    assert "Do not invoke `rollback-lan` while Cloudflare still points to loopback." in runbook


def test_source_defaults_document_final_loopback_but_operator_does_not_edit_env() -> None:
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    operator = OPERATOR.read_text(encoding="utf-8")

    assert "DEALS_BIND_IP=127.0.0.1" in env
    assert "DEALS_BIND_IP=192.168.0.180" not in env
    assert '${DEALS_BIND_IP:-127.0.0.1}:${DEALS_HTTP_PORT:-9128}:80' in compose

    # Phase A reads the production bind but deliberately leaves the real .env
    # unchanged until the separately reviewed final loopback-only phase.
    assert "read_bind_ip()" in operator
    assert not re.search(r"open\([^\n]+['\"]r\+['\"]", operator)
    assert "PY_ENV_WRITE" not in operator


def test_runbook_preserves_control_plane_boundary_and_staged_finalization() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    for marker in (
        "without an avoidable origin outage window",
        "No wildcard `0.0.0.0:9128` publish is permitted.",
        "Phase C — temporary dual bind",
        "Phase D — separately authorized Cloudflare route cutover",
        "authenticated browser/service-auth check",
        "Phase A deliberately does **not** remove the LAN binding",
        "change only the production `DEALS_BIND_IP` value to `127.0.0.1`",
        "The issue remains open until that final phase is complete.",
    ):
        assert marker in text
