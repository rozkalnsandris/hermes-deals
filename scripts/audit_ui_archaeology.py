#!/usr/bin/env python3
"""Emit a deterministic, content-only inventory of Hermes Deals UI archaeology.

This tool is intentionally conservative. It does not decide that a CSS rule is dead;
Chrome Coverage plus interaction/visual evidence must justify destructive cleanup.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "backend" / "app" / "ui"
STYLES = UI_ROOT / "styles.css"
INDEX = UI_ROOT / "index.html"
APP = UI_ROOT / "app.js"
CONTRACT = UI_ROOT / "ui-architecture-contract.json"

STYLE_OPEN_RE = re.compile(r"HERMES_UI_STYLE_OPEN:([A-Za-z0-9+/=]+)")
STYLE_ID_RE = re.compile(r'<style\s+id=["\']([^"\']+)["\']', re.IGNORECASE)
FIX_META_RE = re.compile(
    r'<meta\s+name=["\']hermes-ui-fix["\']\s+content=["\']([^"\']+)["\']\s*/?>',
    re.IGNORECASE,
)
BUNDLE_META_RE = re.compile(
    r'<meta\s+name=["\']hermes-ui-bundle["\']\s+content=["\']([^"\']+)["\']\s*/?>',
    re.IGNORECASE,
)
RELEASE_META_RE = re.compile(
    r'<meta\s+name=["\']hermes-ui-release["\']\s+content=["\']([^"\']+)["\']\s*/?>',
    re.IGNORECASE,
)
BODY_RE = re.compile(r"<body\b([^>]*)>", re.IGNORECASE)
CLASS_RE = re.compile(r'class=["\']([^"\']*)["\']', re.IGNORECASE)
DATA_RELEASE_RE = re.compile(r'data-ui-release=["\']([^"\']+)["\']', re.IGNORECASE)
ARCHIVE_COMMENT_RE = re.compile(
    r"<!--(?:(?!-->).)*(?:archived|test-lineage|legacy contract markers)(?:(?!-->).)*-->",
    re.IGNORECASE | re.DOTALL,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _decode_style_tag(encoded: str) -> str:
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except Exception as exc:  # pragma: no cover - defensive fail-closed diagnostic
        raise ValueError(f"invalid HERMES_UI_STYLE_OPEN marker: {encoded}") from exc


def _style_fragment_ids(css: str) -> list[str]:
    result: list[str] = []
    for encoded in STYLE_OPEN_RE.findall(css):
        tag = _decode_style_tag(encoded)
        match = STYLE_ID_RE.search(tag)
        result.append(match.group(1) if match else "anonymous-base")
    return result


def _first(regex: re.Pattern[str], text: str) -> str | None:
    match = regex.search(text)
    return match.group(1) if match else None


def build_report() -> dict[str, object]:
    css = _read(STYLES)
    html = _read(INDEX)
    js = _read(APP)
    contract = json.loads(_read(CONTRACT))

    body_match = BODY_RE.search(html)
    body_attrs = body_match.group(1) if body_match else ""
    body_classes_match = CLASS_RE.search(body_attrs)
    body_classes = body_classes_match.group(1).split() if body_classes_match else []

    style_fragment_ids = _style_fragment_ids(css)
    fix_markers = FIX_META_RE.findall(html)
    legacy_helpers = contract["w5_freeze"]["legacy_daily_special_helpers"]
    explicit_tokens = contract["w5_freeze"]["explicit_daily_special_contract_tokens"]

    return {
        "schema_version": 1,
        "files": {
            "styles_css_bytes": STYLES.stat().st_size,
            "index_html_bytes": INDEX.stat().st_size,
            "app_js_bytes": APP.stat().st_size,
        },
        "active_release": {
            "bundle_meta": _first(BUNDLE_META_RE, html),
            "release_meta": _first(RELEASE_META_RE, html),
            "body_classes": body_classes,
            "body_data_ui_release": _first(DATA_RELEASE_RE, body_attrs),
        },
        "css_archaeology": {
            "style_fragment_count": len(style_fragment_ids),
            "style_fragment_ids": style_fragment_ids,
            "important_declaration_count": css.count("!important"),
            "desktop_body_zoom_workaround_present": bool(
                re.search(r"@media\s*\(min-width:1000px\)\s*\{\s*body\s*\{\s*zoom\s*:\s*\.8", css)
            ),
            "cascade_layer_declaration_present": "@layer" in css,
        },
        "html_archaeology": {
            "fix_marker_count": len(fix_markers),
            "fix_markers": fix_markers,
            "archived_contract_comment_count": len(ARCHIVE_COMMENT_RE.findall(html)),
        },
        "javascript_archaeology": {
            "legacy_daily_special_helpers": {
                token: token in js for token in legacy_helpers
            },
            "explicit_daily_special_contract": {
                token: token in js for token in explicit_tokens
            },
        },
        "target_css_hierarchy": contract["w5_freeze"]["target_css_hierarchy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit one-line JSON instead of indented deterministic JSON",
    )
    args = parser.parse_args()
    report = build_report()
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
            separators=(",", ":") if args.compact else None,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
