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

    source.joinpath("ui-architecture-contract.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_release": {
                    "bundle_meta": "minimal-v2",
                    "release": "reference-v1",
                    "body_classes": ["ui2-control-room", "ui-minimal-v2"],
                    "production_asset_mode": "hashed-w4",
                    "production_cache_policy": "w4c-immutable",
                },
                "w5_freeze": {
                    "legacy_daily_special_helpers": [
                        "DAILY_SPECIAL_PAGE_LIMIT",
                        "DAILY_SPECIAL_MAX_PAGES",
                        "legacyCurrentDealDailySpecialContract",
                        "dailySpecialsUrl",
                        "fetchAllDailyDeals",
                    ],
                    "explicit_daily_special_contract_tokens": [
                        "/api/v1/deals/daily-specials",
                        "explicit_immutable_retailer_evidence_only",
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source.joinpath("index.html").write_text(
        """<!doctype html>
<html><head>
<meta name="hermes-ui-bundle" content="minimal-v2">
<meta name="hermes-ui-release" content="reference-v1">
<link rel="stylesheet" href="/ui/styles.css">
</head><body class="ui2-control-room ui-minimal-v2" data-ui-release="reference-v1">
<div class="ui2-shell reference-app">
<h1 id="weeklyOverviewTitle">Weekly</h1>
<section id="dailySpecialsSection"></section>
</div>
<script src="/ui/weekly-payload-bridge.js"></script>
<script src="/ui/app.js"></script>
</body></html>
""",
        encoding="utf-8",
    )

    js_relative = "assets/w4-entry.abcdefgh.js"
    css_relative = "assets/w4-entry.ijklmnop.css"
    js = (
        b'console.log("w3-behavior-preserving-bootstrap-v1",'
        b'"/api/v1/deals/daily-specials",'
        b'"explicit_immutable_retailer_evidence_only");\n'
    )
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
    assert "hermes-ui-fix" not in html

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
        'console.log("w3-behavior-preserving-bootstrap-v1 changed",'
        '"/api/v1/deals/daily-specials",'
        '"explicit_immutable_retailer_evidence_only");\n',
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


def test_w4_shadow_package_rejects_historical_fix_metadata(tmp_path: Path) -> None:
    source, build = _fixture(tmp_path)
    index_path = source / "index.html"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace(
            "</head>",
            '<meta name="hermes-ui-fix" content="should-not-return">\n</head>',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(W4ShadowError, match="historical hermes-ui-fix metadata"):
        build_w4_shadow_package(source, build)


def test_w4_shadow_package_rejects_release_contract_drift(tmp_path: Path) -> None:
    source, build = _fixture(tmp_path)
    contract_path = source / "ui-architecture-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["active_release"]["release"] = "drifted-release"
    contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")

    with pytest.raises(W4ShadowError, match="source UI release metadata"):
        build_w4_shadow_package(source, build)


def test_w4_shadow_package_rejects_missing_explicit_daily_special_contract(
    tmp_path: Path,
) -> None:
    source, build = _fixture(tmp_path)
    js_path = build / "assets" / "w4-entry.abcdefgh.js"
    js = b'console.log("w3-behavior-preserving-bootstrap-v1");\n'
    js_path.write_bytes(js)
    evidence_path = build / "w4-shadow-build.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["js"]["bytes"] = len(js)
    evidence["js"]["sha256"] = _digest(js)
    evidence_path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")

    with pytest.raises(W4ShadowError, match="lost explicit daily-special contract"):
        build_w4_shadow_package(source, build)
