from __future__ import annotations

import base64
from pathlib import Path
import re
from typing import Any


UI_DIR = Path(__file__).resolve().parents[1] / "app" / "ui"
UI_INDEX_PATH = UI_DIR / "index.html"
UI_STYLE_PATH = UI_DIR / "styles.css"
UI_APP_PATH = UI_DIR / "app.js"
UI_WEEKLY_BRIDGE_PATH = UI_DIR / "weekly-payload-bridge.js"
CSS_TRAILING_WS_PATCHES = [(19626, 'ICA=')]
JS_TRAILING_WS_PATCHES = []

_STYLESHEET_LINK = '<link rel="stylesheet" href="/ui/styles.css">'
_WEEKLY_PAYLOAD_BRIDGE_SCRIPT = '<script src="/ui/weekly-payload-bridge.js"></script>'
_APPLICATION_SCRIPT = '<script src="/ui/app.js"></script>'
_BRANDING_FAVICON_BLOCK = """  <!-- hermes-branding-overlay:start -->
  <link rel=\"icon\" type=\"image/png\" sizes=\"96x96\" href=\"/ui/assets/deals-logo.png\">
  <link rel=\"shortcut icon\" type=\"image/x-icon\" href=\"/ui/assets/deals-logo.ico\">
  <!-- hermes-branding-overlay:end -->
"""
_BRAND_LOGO = (
    '<img class="project-logo" src="/ui/assets/deals-logo.svg" '
    'width="34" height="34" alt="">'
)
_WEEKLY_BRAND_LOGO = (
    '<img class="project-logo weekly-project-logo" '
    'src="/ui/assets/deals-logo.svg" width="32" height="32" alt="">'
)
_MARKER = re.compile(
    r"/\*HERMES_UI_(?:STYLE|SCRIPT)_(?:OPEN|CLOSE|GAP):"
    r"([A-Za-z0-9+/=]+)\*/"
)


def _restore_trailing_horizontal_whitespace(
    asset: str,
    patches: list[tuple[int, str]],
) -> str:
    restored = asset
    for offset, encoded in reversed(patches):
        whitespace = base64.b64decode(encoded).decode("utf-8")
        restored = restored[:offset] + whitespace + restored[offset:]
    return restored


def _restore_tags(asset: str) -> str:
    def decode(match: re.Match[str]) -> str:
        return base64.b64decode(match.group(1)).decode("utf-8")

    restored = _MARKER.sub(decode, asset)
    if "HERMES_UI_" in restored:
        raise AssertionError("unresolved UI block marker")
    return restored


def _strip_branding_overlay(source: str) -> str:
    if "hermes-branding-overlay:start" not in source:
        return source
    if source.count(_BRANDING_FAVICON_BLOCK) != 1:
        raise AssertionError("UI branding favicon overlay contract is not exact")
    if source.count(_BRAND_LOGO) != 2:
        raise AssertionError("UI branding logo overlay contract is not exact")
    if source.count(_WEEKLY_BRAND_LOGO) != 1:
        raise AssertionError("UI weekly branding overlay contract is not exact")
    restored = source.replace(_BRANDING_FAVICON_BLOCK, "", 1)
    restored = restored.replace(_BRAND_LOGO, "")
    restored = restored.replace(_WEEKLY_BRAND_LOGO + "\n              ", "", 1)
    restored = restored.replace(
        '<svg class="brand-leaf" hidden',
        '<svg class="brand-leaf"',
    )
    restored = restored.replace(
        '<svg class="weekly-brand-mark" hidden',
        '<svg class="weekly-brand-mark"',
        1,
    )
    return restored


def read_family_ui_contract(html: str | None = None) -> str:
    source = (
        UI_INDEX_PATH.read_text(encoding="utf-8")
        if html is None
        else html
    )
    source = _strip_branding_overlay(source)
    if source.count(_STYLESHEET_LINK) != 1:
        raise AssertionError("UI stylesheet link contract is not exact")
    if source.count(_WEEKLY_PAYLOAD_BRIDGE_SCRIPT) != 1:
        raise AssertionError("UI weekly payload bridge contract is not exact")
    if source.count(_APPLICATION_SCRIPT) != 1:
        raise AssertionError("UI application script contract is not exact")
    if source.index(_WEEKLY_PAYLOAD_BRIDGE_SCRIPT) > source.index(_APPLICATION_SCRIPT):
        raise AssertionError("UI weekly payload bridge must load before the application")

    styles = _restore_tags(
        _restore_trailing_horizontal_whitespace(
            UI_STYLE_PATH.read_text(encoding="utf-8"),
            CSS_TRAILING_WS_PATCHES,
        )
    )
    application = _restore_tags(
        _restore_trailing_horizontal_whitespace(
            UI_APP_PATH.read_text(encoding="utf-8"),
            JS_TRAILING_WS_PATCHES,
        )
    )
    legacy_source = source.replace(_WEEKLY_PAYLOAD_BRIDGE_SCRIPT, "", 1)
    return legacy_source.replace(
        _STYLESHEET_LINK,
        styles,
        1,
    ).replace(
        _APPLICATION_SCRIPT,
        application,
        1,
    )


def ui_response_contract(response: Any) -> str:
    return read_family_ui_contract(response.text)
