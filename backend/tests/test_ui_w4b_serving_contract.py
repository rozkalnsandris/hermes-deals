from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "backend" / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
NGINX = ROOT / "infra" / "nginx.conf"
RUNTIME = ROOT / "backend" / "app" / "runtime.py"
MAIN = ROOT / "backend" / "app" / "main.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_w4_runtime_mode_is_explicit_default_inline_and_fail_closed() -> None:
    runtime = read(RUNTIME)
    compose = read(COMPOSE)

    assert 'INLINE_W3 = "inline-w3"' in runtime
    assert 'HASHED_W4 = "hashed-w4"' in runtime
    assert "ALLOWED_UI_ASSET_MODES" in runtime
    assert 'os.getenv("HERMES_UI_ASSET_MODE", DEFAULT_UI_ASSET_MODE)' in runtime
    assert "raise UiAssetRuntimeError" in runtime
    assert "w4-shadow-package.json" in runtime
    assert 'package.get("result") != "PASS"' in runtime
    assert "production_inline_bundle_preserved" in runtime
    assert 'path.startswith("/ui/assets/")' in runtime
    assert '"application/javascript"' in runtime
    assert '"text/css"' in runtime
    assert 'HTML_CACHE_CONTROL = "no-cache"' in runtime
    assert 'HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"' in runtime
    assert '"Cache-Control": cache_control' in runtime
    assert 'cache_control=HASHED_ASSET_CACHE_CONTROL' in runtime
    assert 'cache_control=HTML_CACHE_CONTROL' in runtime
    assert '"X-Hermes-UI-Asset-Mode": self.mode' in runtime
    assert "HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}" in compose


def test_w4_keeps_main_w3_routes_and_review_ui_unchanged() -> None:
    runtime = read(RUNTIME)
    main = read(MAIN)

    assert "from app.main import app as main_app" in runtime
    assert 'if path == "/ui" and self.mode == HASHED_W4:' in runtime
    assert "await self.wrapped_app(scope, receive, send)" in runtime
    assert 'UI_DIR = Path(__file__).resolve().parent / "ui"' in main
    assert '@app.get("/ui", response_class=HTMLResponse' in main
    assert '@app.get("/ui/styles.css"' in main
    assert '@app.get("/ui/app.js"' in main
    assert '"/ui/review"' in main


def test_w4c_release_keeps_nginx_as_transparent_asset_proxy() -> None:
    dockerfile = read(DOCKERFILE)
    nginx = read(NGINX)

    assert 'CMD ["uvicorn", "app.runtime:app"' in dockerfile
    assert "python -m app.ui_bundle --ui-dir /app/app/ui" in dockerfile
    assert "COPY --from=ui-build /ui/dist-w4 /app/app/ui_w4_shadow" in dockerfile
    assert "location ^~ /ui/assets/" in nginx
    assert nginx.count("proxy_pass http://api:8000;") >= 4

    asset_block = nginx.split("location ^~ /ui/assets/", 1)[1].split("}", 1)[0]
    assert "proxy_pass http://api:8000;" in asset_block
    assert "add_header" not in asset_block
    assert "expires" not in asset_block
    assert "immutable" not in asset_block.casefold()
    assert "max-age" not in asset_block.casefold()
