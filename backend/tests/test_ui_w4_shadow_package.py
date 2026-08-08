from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.ui_w4_shadow import W4ShadowError, build_w4_shadow_package


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "ui"
    build = tmp_path / "dist-w4"
    (build / ".vite").mkdir(parents=True)
    (build / "assets").mkdir()
    source.mkdir()

    source.joinpath("index.html").write_text(
        """<!doctype html>
<html><head>
<meta name="x" content="reference-v11-explicit-daily-special-api">
<meta name="x" content="weekly-overview-v6-active-retailer-compaction">
<meta name="x" content="netto-daily-quality-v1">
<link rel="stylesheet" href="/ui/styles.css">
</head><body><div class="ui2-shell reference-app"></div>
<script src="/ui/weekly-payload-bridge.js"></script>
<script src="/ui/app.js"></script>
</body></html>
""",
        encoding="utf-8",
    )

    js_relative = "assets/w4-entry.abcdefgh.js"
    css_relative = "assets/w4-entry.ijklmnop.css"
    js = b'console.log("w3-behavior-preserving-bootstrap-v1");\n'
    css = b'/* HERMES_UI_STYLE_OPEN: fixture */\nbody{margin:0}\n'
    build.joinpath(js_relative).write_bytes(js)
    build.joinpath(css_relative).write_bytes(css)

    manifest = {
        "src/w4-entry.js": {
            "file": js_relative,
            "name": "w4-entry",
            "src": "src/w4-entry.js",
            "isEntry": True,
            "css": [css_relative],
        }
    }
    manifest_bytes = (json.dumps(manifest, separators=(",", ":")) + "\n").encode()
    build.joinpath(".vite/manifest.json").write_bytes(manifest_bytes)
    build.joinpath("w4-shadow-build.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "version": "w4a-shadow-build-v1",
                "base": "/ui/",
                "entry": "src/w4-entry.js",
                "js": {
                    "path": js_relative,
                    "bytes": len(js),
                    "sha256": _digest(js),
                },
                "css": {
                    "path": css_relative,
                    "bytes": len(css),
                    "sha256": _digest(css),
                },
                "manifest": {
                    "path": ".vite/manifest.json",
                    "bytes": len(manifest_bytes),
                    "sha256": _digest(manifest_bytes),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return source, build


def test_w4_shadow_package_rewrites_only_manifest_assets(tmp_path: Path) -> None:
    source, build = _fixture(tmp_path)

    index_path = build_w4_shadow_package(source, build)

    html = index_path.read_text(encoding="utf-8")
    assert '<meta name="hermes-w4-shadow" content="hashed-assets-v1">' in html
    assert '<link rel="stylesheet" href="/ui/assets/w4-entry.ijklmnop.css">' in html
    assert '<script type="module" src="/ui/assets/w4-entry.abcdefgh.js"></script>' in html
    assert "/ui/styles.css" not in html
    assert "/ui/app.js" not in html
    assert "/ui/weekly-payload-bridge.js" not in html
    assert "data-hermes-production-bundle" not in html

    package = json.loads(build.joinpath("w4-shadow-package.json").read_text())
    assert package["result"] == "PASS"
    assert package["serving_enabled"] is False
    assert package["production_inline_bundle_preserved"] is True
    assert package["js"]["sha256"] == _digest(
        build.joinpath("assets/w4-entry.abcdefgh.js").read_bytes()
    )
    assert package["css"]["sha256"] == _digest(
        build.joinpath("assets/w4-entry.ijklmnop.css").read_bytes()
    )


def test_w4_shadow_package_fails_closed_on_asset_drift(tmp_path: Path) -> None:
    source, build = _fixture(tmp_path)
    build.joinpath("assets/w4-entry.abcdefgh.js").write_text(
        'console.log("w3-behavior-preserving-bootstrap-v1 changed");\n',
        encoding="utf-8",
    )

    with pytest.raises(W4ShadowError, match="evidence mismatch for js"):
        build_w4_shadow_package(source, build)


def test_w4_shadow_package_rejects_unhashed_manifest_entry(tmp_path: Path) -> None:
    source, build = _fixture(tmp_path)
    manifest_path = build / ".vite" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["src/w4-entry.js"]["file"] = "assets/w4-entry.js"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(W4ShadowError, match="entry JS is not content-hashed"):
        build_w4_shadow_package(source, build)
