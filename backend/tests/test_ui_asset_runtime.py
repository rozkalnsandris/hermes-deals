from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
import pytest

from app.runtime import (
    HASHED_W4,
    INLINE_W3,
    UiAssetModeApp,
    UiAssetRuntimeError,
    resolve_ui_asset_mode,
)


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _shadow_package(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "ui_w4_shadow"
    (root / "assets").mkdir(parents=True)
    (root / ".vite").mkdir()

    js_relative = "assets/w4-entry.abcdefgh.js"
    css_relative = "assets/w4-entry.ijklmnop.css"
    js = b'console.log("w3-behavior-preserving-bootstrap-v1");\n'
    css = b'/* HERMES_UI_STYLE_OPEN: runtime fixture */\nbody{margin:0}\n'
    html = (
        "<!doctype html><html><head>"
        '<meta name="hermes-w4-shadow" content="hashed-assets-v1">'
        f'<link rel="stylesheet" href="/ui/{css_relative}">'
        "</head><body>W4 preview"
        f'<script type="module" src="/ui/{js_relative}"></script>'
        "</body></html>\n"
    ).encode()
    manifest = json.dumps(
        {
            "src/w4-entry.js": {
                "file": js_relative,
                "isEntry": True,
                "css": [css_relative],
            }
        },
        separators=(",", ":"),
    ).encode()

    root.joinpath("index.html").write_bytes(html)
    root.joinpath(js_relative).write_bytes(js)
    root.joinpath(css_relative).write_bytes(css)
    root.joinpath(".vite/manifest.json").write_bytes(manifest)
    root.joinpath("w4-shadow-package.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "version": "w4a-shadow-package-v1",
                "html": {
                    "path": "index.html",
                    "bytes": len(html),
                    "sha256": _sha(html),
                },
                "manifest": {
                    "path": ".vite/manifest.json",
                    "bytes": len(manifest),
                    "sha256": _sha(manifest),
                },
                "js": {
                    "path": js_relative,
                    "bytes": len(js),
                    "sha256": _sha(js),
                },
                "css": {
                    "path": css_relative,
                    "bytes": len(css),
                    "sha256": _sha(css),
                },
                "serving_enabled": False,
                "production_inline_bundle_preserved": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root, js_relative, css_relative


def _wrapped_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ui")
    def inline_ui() -> PlainTextResponse:
        return PlainTextResponse("inline-w3")

    @app.get("/ui/app.js")
    def inline_app() -> PlainTextResponse:
        return PlainTextResponse("legacy-app")

    @app.get("/ui/review")
    def review() -> PlainTextResponse:
        return PlainTextResponse("review-ui")

    return app


def test_asset_mode_allowlist_defaults_to_inline_w3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERMES_UI_ASSET_MODE", raising=False)
    assert resolve_ui_asset_mode() == INLINE_W3
    monkeypatch.setenv("HERMES_UI_ASSET_MODE", HASHED_W4)
    assert resolve_ui_asset_mode() == HASHED_W4
    with pytest.raises(UiAssetRuntimeError, match="invalid HERMES_UI_ASSET_MODE"):
        resolve_ui_asset_mode("preview")


def test_inline_w3_is_passthrough_and_hashed_namespace_is_closed(tmp_path: Path) -> None:
    root, js_relative, _ = _shadow_package(tmp_path)
    client = TestClient(UiAssetModeApp(_wrapped_app(), mode=INLINE_W3, shadow_dir=root))

    assert client.get("/ui").text == "inline-w3"
    assert client.get("/ui/app.js").text == "legacy-app"
    assert client.get("/ui/review").text == "review-ui"
    assert client.get(f"/ui/{js_relative}").status_code == 404


def test_hashed_w4_serves_only_package_proven_assets_and_keeps_rollback_endpoints(
    tmp_path: Path,
) -> None:
    root, js_relative, css_relative = _shadow_package(tmp_path)
    client = TestClient(UiAssetModeApp(_wrapped_app(), mode=HASHED_W4, shadow_dir=root))

    ui = client.get("/ui")
    assert ui.status_code == 200
    assert 'hermes-w4-shadow" content="hashed-assets-v1"' in ui.text
    assert f'/ui/{js_relative}' in ui.text
    assert f'/ui/{css_relative}' in ui.text
    assert "/ui/app.js" not in ui.text
    assert "/ui/styles.css" not in ui.text
    assert ui.headers["x-hermes-ui-asset-mode"] == HASHED_W4
    assert ui.headers["cache-control"] == "no-store"

    js = client.get(f"/ui/{js_relative}")
    css = client.get(f"/ui/{css_relative}")
    assert js.status_code == 200
    assert js.headers["content-type"] == "application/javascript"
    assert "w3-behavior-preserving-bootstrap-v1" in js.text
    assert css.status_code == 200
    assert css.headers["content-type"] == "text/css"
    assert "HERMES_UI_STYLE_OPEN:" in css.text

    assert client.get("/ui/assets/not-in-package.js").status_code == 404
    assert client.get("/ui/assets/../w4-shadow-package.json").status_code == 404
    assert client.get("/ui/app.js").text == "legacy-app"
    assert client.get("/ui/review").text == "review-ui"


def test_hashed_w4_head_requests_return_no_body(tmp_path: Path) -> None:
    root, js_relative, _ = _shadow_package(tmp_path)
    client = TestClient(UiAssetModeApp(_wrapped_app(), mode=HASHED_W4, shadow_dir=root))

    assert client.head("/ui").status_code == 200
    asset = client.head(f"/ui/{js_relative}")
    assert asset.status_code == 200
    assert asset.content == b""


def test_hashed_w4_fails_closed_if_packaged_asset_drifted(tmp_path: Path) -> None:
    root, js_relative, _ = _shadow_package(tmp_path)
    root.joinpath(js_relative).write_text(
        'console.log("w3-behavior-preserving-bootstrap-v1 drift");\n',
        encoding="utf-8",
    )

    with pytest.raises(UiAssetRuntimeError, match="integrity mismatch for W4 JavaScript"):
        UiAssetModeApp(_wrapped_app(), mode=HASHED_W4, shadow_dir=root)
