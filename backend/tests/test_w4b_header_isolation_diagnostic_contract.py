from __future__ import annotations

from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools/runner/w4b/run-w4b-header-isolation-diagnostic.sh"
TARGET_SHA = "128325461f249791af8a5653163772e955dd2b89"


def read_script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_w4b_header_diagnostic_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_w4b_header_diagnostic_is_exact_target_and_unpublished() -> None:
    source = read_script()

    assert f"TARGET_SHA='{TARGET_SHA}'" in source
    assert 'TARGET_IMAGE="hermes-deals-api:w4b-$TARGET_SHORT"' in source
    assert 'TARGET_NGINX="$TARGET_ROOT/source/infra/nginx.conf"' in source
    assert "NGINX_IMAGE='nginx:1.30.4-alpine'" in source
    assert source.count("--pull=never") == 2
    assert "--network-alias api" in source
    assert "--publish" not in source
    assert "PortBindings" in source
    assert "diagnostic_api_has_published_ports" in source
    assert "diagnostic_web_has_published_ports" in source


def test_w4b_header_diagnostic_never_mutates_production_services_or_db() -> None:
    source = read_script()

    forbidden = (
        "docker compose",
        "docker restart",
        "docker stop",
        "docker start",
        "docker exec $DB_BEFORE",
        "alembic upgrade",
        "psql ",
        "/api/health",
        "cloudflared restart",
        "cloudflared stop",
        "cloudflared start",
        "systemctl restart",
        "systemctl stop",
        "systemctl start",
        "ufw ",
        "git reset",
        "git clean",
        "git checkout",
        "git pull",
    )
    for token in forbidden:
        assert token not in source

    assert "postgresql+psycopg://diag:diag@127.0.0.1:9/diag" in source
    assert "HERMES_UI_ASSET_MODE=hashed-w4" in source
    assert source.count("PRODUCTION_MUTATED=false") >= 2


def test_w4b_header_diagnostic_proves_direct_and_proxy_paths_separately() -> None:
    source = read_script()

    assert "http://127.0.0.1:8000/ui" in source
    assert 'http://$DIAG_WEB/ui' in source
    assert 'response.headers.get("X-Hermes-UI-Asset-Mode")' in source
    assert 'response.headers.get("Cache-Control")' in source
    assert 'hermes-w4-shadow' in source
    assert "DIAGNOSIS='DIRECT_API_RUNTIME'" in source
    assert "DIAGNOSIS='NGINX_PROXY_PATH'" in source
    assert "DIAGNOSIS='TRANSITION_PATH_OR_TIMING'" in source
    assert "DIRECT_MODE=%s" in source
    assert "PROXY_MODE=%s" in source


def test_w4b_header_diagnostic_guards_production_and_cloudflared_identity() -> None:
    source = read_script()

    assert 'API_BEFORE="$(single_service_container api)"' in source
    assert 'WEB_BEFORE="$(single_service_container web)"' in source
    assert 'DB_BEFORE="$(single_service_container db)"' in source
    assert 'CLOUDFLARED_BEFORE="$(cloudflared_pid)"' in source
    assert "production_api_changed" in source
    assert "production_web_changed" in source
    assert "production_db_changed" in source
    assert "cloudflared_changed" in source
    assert "PRODUCTION_RUNTIME_UNCHANGED=true" in source
    assert "CLOUDFLARED_UNCHANGED=true" in source
