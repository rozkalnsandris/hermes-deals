from __future__ import annotations

import base64
from pathlib import Path
import re
from typing import Any


UI_DIR = Path(__file__).resolve().parents[1] / "app" / "ui"
UI_INDEX_PATH = UI_DIR / "index.html"
UI_STYLE_PATH = UI_DIR / "styles.css"
UI_APP_PATH = UI_DIR / "app.js"
ORIGINAL_INDEX_SHA256 = "3b955332d97a732197122e9cc09bd50eb74b0467acd1f51dfe0da059b5c1e798"
CSS_TRAILING_WS_PATCHES = [(19626, 'ICA=')]
JS_TRAILING_WS_PATCHES = []

_STYLESHEET_LINK = '<link rel="stylesheet" href="/ui/styles.css">'
_APPLICATION_SCRIPT = '<script src="/ui/app.js"></script>'
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


def read_family_ui_contract(html: str | None = None) -> str:
    source = (
        UI_INDEX_PATH.read_text(encoding="utf-8")
        if html is None
        else html
    )
    if source.count(_STYLESHEET_LINK) != 1:
        raise AssertionError("UI stylesheet link contract is not exact")
    if source.count(_APPLICATION_SCRIPT) != 1:
        raise AssertionError("UI application script contract is not exact")

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
    return source.replace(
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
