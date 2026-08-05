from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
MAIN_DEPLOY = ROOT / "tools/runner/release/hermes-deals-release-main-deploy"


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


def test_direct_main_deploy_keeps_public_verification_outside_root_helper() -> None:
    text = MAIN_DEPLOY.read_text(encoding="utf-8")
    assert "https://deals.rozkalns.net" not in text

    launcher = (ROOT / "tools/vscode-rpi5-release.sh").read_text(encoding="utf-8")
    assert "https://deals.rozkalns.net/api/health" in launcher
    assert "https://deals.rozkalns.net/ui" in launcher
