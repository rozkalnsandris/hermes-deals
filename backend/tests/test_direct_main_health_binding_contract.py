from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
MAIN_DEPLOY = ROOT / "tools/runner/release/hermes-deals-release-main-deploy"
DISPATCHER = ROOT / "tools/runner/release/hermes-deals-release-dispatch"


def test_direct_main_deploy_resolves_exact_web_published_binding() -> None:
    subprocess.run(["bash", "-n", str(MAIN_DEPLOY)], check=True)
    text = MAIN_DEPLOY.read_text(encoding="utf-8")

    for marker in (
        "resolve_web_health_url()",
        'WEB_BEFORE="$("${COMPOSE[@]}" ps -q web)"',
        'ports.get("80/tcp")',
        'len(bindings) != 1',
        'binding.get("HostIp")',
        'binding.get("HostPort")',
        'host_ip in {"", "0.0.0.0", "::"}',
        "ipaddress.ip_address(host_ip)",
        'LOCAL_HEALTH_URL="$(resolve_web_health_url "$WEB_BEFORE")"',
        'curl --fail --silent --show-error --max-time 8 "$LOCAL_HEALTH_URL"',
        "production web container changed during registration",
        "production web container changed during API/UI deploy",
        'POST_HEALTH_URL="$(resolve_web_health_url "$WEB_AFTER")"',
        "production web published health endpoint changed during API/UI deploy",
        'LOCAL_HEALTH_URL=%s',
    ):
        assert marker in text

    assert "http://127.0.0.1:9128/api/health" not in text
    assert "192.168.0.180" not in text


def test_dispatcher_reuses_exact_web_published_binding_for_apply_and_rollback() -> None:
    subprocess.run(["bash", "-n", str(DISPATCHER)], check=True)
    text = DISPATCHER.read_text(encoding="utf-8")

    for marker in (
        "resolve_web_base_url()",
        'WEB_CONTAINER_BEFORE="$("${COMPOSE[@]}" ps -q web)"',
        'ports.get("80/tcp")',
        'binding.get("HostIp")',
        'binding.get("HostPort")',
        'LOCAL_WEB_BASE="$(resolve_web_base_url "$WEB_CONTAINER_BEFORE")"',
        '"$LOCAL_WEB_BASE/api/health"',
        '"$LOCAL_WEB_BASE/ui"',
        'WEB_CONTAINER_AFTER="$("${COMPOSE[@]}" ps -q web)"',
        'WEB_CONTAINER_RESTORED="$("${COMPOSE[@]}" ps -q web)"',
        '"$WEB_CONTAINER_AFTER" == "$WEB_CONTAINER_BEFORE"',
        '"$WEB_CONTAINER_RESTORED" == "$WEB_CONTAINER_BEFORE"',
        'APPLY_LOG="$STAGING_DIR/apply-compose.log"',
        'ROLLBACK_LOG="$STAGING_DIR/rollback-compose.log"',
        "production API health check failed before deploy",
        "production API apply verification failed",
        "production API rollback verification failed",
    ):
        assert marker in text

    assert "127.0.0.1:9128" not in text
    assert "192.168.0.180" not in text


def test_direct_main_deploy_keeps_public_verification_outside_root_helper() -> None:
    text = MAIN_DEPLOY.read_text(encoding="utf-8")
    assert "https://deals.rozkalns.net" not in text

    launcher = (ROOT / "tools/vscode-rpi5-release.sh").read_text(encoding="utf-8")
    assert "https://deals.rozkalns.net/api/health" in launcher
    assert "https://deals.rozkalns.net/ui" in launcher
