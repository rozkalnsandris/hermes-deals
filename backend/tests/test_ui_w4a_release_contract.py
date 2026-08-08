from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
MAIN = REPO_ROOT / "backend" / "app" / "main.py"
PACKAGE = REPO_ROOT / "backend" / "frontend" / "package.json"
W4_CONFIG = REPO_ROOT / "backend" / "frontend" / "vite.w4.config.js"


def test_w4a_release_image_packages_shadow_without_serving_cutover() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    main = MAIN.read_text(encoding="utf-8")

    assert "npm run build:check" in dockerfile
    assert "npm run build:w4:check" in dockerfile
    assert "COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js" in dockerfile
    assert "COPY --from=ui-build /ui/dist-w4 /app/app/ui_w4_shadow" in dockerfile
    assert "python -m app.ui_w4_shadow" in dockerfile
    assert "python -m app.ui_bundle --ui-dir /app/app/ui" in dockerfile
    assert dockerfile.index("python -m app.ui_w4_shadow") < dockerfile.index(
        "python -m app.ui_bundle --ui-dir /app/app/ui"
    )

    # W4A packages evidence only. Production route ownership remains the exact
    # W3 /app/app/ui tree until a separately reviewed W4B serving cutover.
    assert "ui_w4_shadow" not in main
    assert 'UI_DIR = Path(__file__).resolve().parent / "ui"' in main
    assert '@app.get("/ui", response_class=HTMLResponse' in main
    assert '@app.get("/ui/app.js"' in main


def test_w4a_build_is_manifested_hashed_and_nested_under_ui() -> None:
    package = PACKAGE.read_text(encoding="utf-8")
    config = W4_CONFIG.read_text(encoding="utf-8")

    assert '"vite": "8.1.5"' in package
    assert '"build:w4:check"' in package
    assert 'base: "/ui/"' in config
    assert "manifest: true" in config
    assert "assetsInlineLimit: 0" in config
    assert 'entryFileNames: "assets/[name].[hash].js"' in config
    assert 'assetFileNames: "assets/[name].[hash][extname]"' in config
    assert "rollupOptions" not in config
    assert "rolldownOptions" in config
