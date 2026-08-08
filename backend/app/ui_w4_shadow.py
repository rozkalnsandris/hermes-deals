from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile


STYLE_LINK = '<link rel="stylesheet" href="/ui/styles.css">'
WEEKLY_BRIDGE_TAG = '<script src="/ui/weekly-payload-bridge.js"></script>'
SCRIPT_TAG = '<script src="/ui/app.js"></script>'
SHADOW_META = '<meta name="hermes-w4-shadow" content="hashed-assets-v1">'
ENTRY_KEY = "src/w4-entry.js"
HASHED_JS = re.compile(r"assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.js")
HASHED_CSS = re.compile(r"assets/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{8,}\.css")

_REQUIRED_HTML_MARKERS = (
    'content="reference-v11-explicit-daily-special-api"',
    'content="weekly-overview-v6-active-retailer-compaction"',
    'content="netto-daily-quality-v1"',
    'class="ui2-shell reference-app"',
)


class W4ShadowError(RuntimeError):
    """Raised when the W4 shadow package cannot be proven self-consistent."""


def _read_required(path: Path, label: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise W4ShadowError(f"{label} is missing or unsafe: {path}")
    return path.read_bytes()


def _decode_utf8(payload: bytes, label: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise W4ShadowError(f"{label} is not valid UTF-8") from exc


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _require_exactly_once(text: str, marker: str, label: str) -> None:
    count = text.count(marker)
    if count != 1:
        raise W4ShadowError(
            f"{label} must occur exactly once; found {count}: {marker}"
        )


def _safe_build_asset(build_dir: Path, relative: str) -> Path:
    candidate = (build_dir / relative).resolve(strict=True)
    try:
        candidate.relative_to(build_dir)
    except ValueError as exc:
        raise W4ShadowError(f"manifest path escapes W4 build: {relative}") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise W4ShadowError(f"manifest asset is missing or unsafe: {relative}")
    return candidate


def build_w4_shadow_package(source_ui_dir: Path, build_dir: Path) -> Path:
    source_ui_dir = source_ui_dir.resolve(strict=True)
    build_dir = build_dir.resolve(strict=True)

    source_html_bytes = _read_required(source_ui_dir / "index.html", "source UI HTML")
    source_html = _decode_utf8(source_html_bytes, "source UI HTML")
    manifest_path = build_dir / ".vite" / "manifest.json"
    manifest_bytes = _read_required(manifest_path, "W4 manifest")
    try:
        manifest = json.loads(_decode_utf8(manifest_bytes, "W4 manifest"))
    except json.JSONDecodeError as exc:
        raise W4ShadowError("W4 manifest is not valid JSON") from exc

    entry = manifest.get(ENTRY_KEY)
    if not isinstance(entry, dict) or entry.get("isEntry") is not True:
        raise W4ShadowError(f"W4 manifest entry is missing: {ENTRY_KEY}")
    js_relative = entry.get("file")
    css_values = entry.get("css")
    if not isinstance(js_relative, str) or HASHED_JS.fullmatch(js_relative) is None:
        raise W4ShadowError("W4 manifest entry JS is not content-hashed")
    if (
        not isinstance(css_values, list)
        or len(css_values) != 1
        or not isinstance(css_values[0], str)
        or HASHED_CSS.fullmatch(css_values[0]) is None
    ):
        raise W4ShadowError("W4 manifest must expose exactly one hashed CSS asset")
    css_relative = css_values[0]

    js_path = _safe_build_asset(build_dir, js_relative)
    css_path = _safe_build_asset(build_dir, css_relative)
    js_bytes = _read_required(js_path, "W4 JavaScript asset")
    css_bytes = _read_required(css_path, "W4 CSS asset")
    js_text = _decode_utf8(js_bytes, "W4 JavaScript asset")
    css_text = _decode_utf8(css_bytes, "W4 CSS asset")
    if "w3-behavior-preserving-bootstrap-v1" not in js_text:
        raise W4ShadowError("W4 JavaScript lost the W3 behavior marker")
    if "HERMES_UI_STYLE_OPEN:" not in css_text:
        raise W4ShadowError("W4 CSS lost the reviewed style marker")

    evidence_path = build_dir / "w4-shadow-build.json"
    evidence_bytes = _read_required(evidence_path, "W4 builder evidence")
    try:
        evidence = json.loads(_decode_utf8(evidence_bytes, "W4 builder evidence"))
    except json.JSONDecodeError as exc:
        raise W4ShadowError("W4 builder evidence is not valid JSON") from exc
    if evidence.get("result") != "PASS" or evidence.get("base") != "/ui/":
        raise W4ShadowError("W4 builder evidence did not pass")
    expected = {
        "js": (js_relative, _sha(js_bytes)),
        "css": (css_relative, _sha(css_bytes)),
        "manifest": (".vite/manifest.json", _sha(manifest_bytes)),
    }
    for key, (relative, digest) in expected.items():
        item = evidence.get(key)
        if not isinstance(item, dict):
            raise W4ShadowError(f"W4 builder evidence is missing {key}")
        if item.get("path") != relative or item.get("sha256") != digest:
            raise W4ShadowError(f"W4 builder evidence mismatch for {key}")

    _require_exactly_once(source_html, STYLE_LINK, "source stylesheet reference")
    _require_exactly_once(source_html, WEEKLY_BRIDGE_TAG, "source weekly bridge reference")
    _require_exactly_once(source_html, SCRIPT_TAG, "source application reference")
    _require_exactly_once(source_html, "</head>", "source HTML head closing tag")
    missing = [marker for marker in _REQUIRED_HTML_MARKERS if marker not in source_html]
    if missing:
        raise W4ShadowError(f"source UI HTML is missing required markers: {missing}")
    if SHADOW_META in source_html or "hermes-production-bundle" in source_html:
        raise W4ShadowError("source UI HTML is already generated")

    style_tag = f'<link rel="stylesheet" href="/ui/{css_relative}">'
    script_tag = f'<script type="module" src="/ui/{js_relative}"></script>'
    shadow_html = source_html.replace(STYLE_LINK, style_tag, 1)
    shadow_html = shadow_html.replace(WEEKLY_BRIDGE_TAG, "", 1)
    shadow_html = shadow_html.replace(SCRIPT_TAG, script_tag, 1)
    shadow_html = shadow_html.replace(
        "</head>",
        f"  {SHADOW_META}\n</head>",
        1,
    )
    if not shadow_html.endswith("\n"):
        shadow_html += "\n"

    for forbidden in (
        STYLE_LINK,
        WEEKLY_BRIDGE_TAG,
        SCRIPT_TAG,
        "<style ",
        "data-hermes-production-bundle=",
    ):
        if forbidden in shadow_html:
            raise W4ShadowError(f"W4 shadow HTML retained forbidden inline/legacy marker: {forbidden}")
    _require_exactly_once(shadow_html, SHADOW_META, "W4 shadow marker")
    _require_exactly_once(shadow_html, style_tag, "W4 hashed stylesheet reference")
    _require_exactly_once(shadow_html, script_tag, "W4 hashed module reference")

    html_bytes = shadow_html.encode("utf-8")
    index_path = build_dir / "index.html"
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=build_dir,
        prefix=".index.w4-shadow.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(html_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, index_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    package = {
        "result": "PASS",
        "version": "w4a-shadow-package-v1",
        "html": {
            "path": "index.html",
            "bytes": len(html_bytes),
            "sha256": _sha(html_bytes),
        },
        "manifest": {
            "path": ".vite/manifest.json",
            "bytes": len(manifest_bytes),
            "sha256": _sha(manifest_bytes),
        },
        "js": {
            "path": js_relative,
            "bytes": len(js_bytes),
            "sha256": _sha(js_bytes),
        },
        "css": {
            "path": css_relative,
            "bytes": len(css_bytes),
            "sha256": _sha(css_bytes),
        },
        "serving_enabled": False,
        "production_inline_bundle_preserved": True,
    }
    package_path = build_dir / "w4-shadow-package.json"
    package_path.write_text(
        json.dumps(package, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("W4_SHADOW_PACKAGE=PASS")
    print(f"W4_SHADOW_HTML_SHA256={package['html']['sha256']}")
    print(f"W4_SHADOW_MANIFEST_SHA256={package['manifest']['sha256']}")
    print(f"W4_SHADOW_JS={js_relative}")
    print(f"W4_SHADOW_CSS={css_relative}")
    print("W4_SHADOW_SERVING_ENABLED=false")
    return index_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package the non-serving Hermes Deals W4A hashed-asset shadow build",
    )
    parser.add_argument("--source-ui-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        build_w4_shadow_package(args.source_ui_dir, args.build_dir)
    except (OSError, W4ShadowError) as exc:
        raise SystemExit(f"W4_SHADOW_PACKAGE=FAIL: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
