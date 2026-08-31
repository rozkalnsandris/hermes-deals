from __future__ import annotations

import argparse
from hashlib import sha256
import os
from pathlib import Path
import tempfile


STYLE_LINK = '<link rel="stylesheet" href="/ui/styles.css">'
WEEKLY_BRIDGE_TAG = '<script src="/ui/weekly-payload-bridge.js"></script>'
SCRIPT_TAG = '<script src="/ui/app.js"></script>'
PRODUCTION_META = '<meta name="hermes-production-bundle" content="inline-v1">'
STYLE_MARKER = 'data-hermes-production-bundle="styles.css"'
SCRIPT_MARKER = 'data-hermes-production-bundle="app.js"'
ACCESSIBILITY_STYLE_FILE = "accessibility-fixes.css"
ACCESSIBILITY_SCRIPT_FILE = "accessibility-fixes.js"
ACCESSIBILITY_MARKER = "HERMES_UI_ACCESSIBILITY_FIXES_V1"
LEGACY_GLOBAL_ZOOM = "@media(min-width:1000px){body{zoom:.8}}"

_REQUIRED_HTML_MARKERS = (
    'content="reference-v11-explicit-daily-special-api"',
    'content="weekly-overview-v6-active-retailer-compaction"',
    'content="netto-daily-quality-v1"',
    'class="ui2-shell reference-app"',
)
_REQUIRED_CSS_MARKERS = (
    "--accent:#246b45",
    "body.ui-minimal-v2",
    "HERMES_UI_STYLE_OPEN:",
)
_REQUIRED_JS_MARKERS = (
    "/api/v1/deals/current",
    "/api/v1/deals/daily-specials",
    "/api/v1/catalog",
    "HERMES_UI_SCRIPT_OPEN:",
    "w3-behavior-preserving-bootstrap-v1",
    "normalized_unique_deals_by_id_v1",
)


class UiBundleError(RuntimeError):
    """Raised when the reviewed split UI cannot form a safe production bundle."""


def _read_required(path: Path, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise UiBundleError(f"{label} is missing or unsafe: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise UiBundleError(f"{label} is not valid UTF-8: {path}") from exc


def _require_exactly_once(text: str, marker: str, label: str) -> None:
    count = text.count(marker)
    if count != 1:
        raise UiBundleError(
            f"{label} must occur exactly once; found {count}: {marker}"
        )


def _require_markers(text: str, markers: tuple[str, ...], label: str) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise UiBundleError(f"{label} is missing required markers: {missing}")


def build_production_ui_bundle(ui_dir: Path) -> Path:
    """Inline reviewed CSS and verified JavaScript into image-only HTML.

    The repository source remains split for review and testing. Docker first
    replaces app.js with the deterministic W3 build output, then invokes this
    function inside the immutable release image. The historical external weekly
    compatibility bridge is removed because W3 now includes it in app.js. The
    bounded W6 accessibility patch is appended after the reviewed base assets so
    it can correct interaction/focus behavior without changing data semantics.
    """

    ui_dir = ui_dir.resolve(strict=True)
    index_path = ui_dir / "index.html"
    style_path = ui_dir / "styles.css"
    app_path = ui_dir / "app.js"
    accessibility_style_path = ui_dir / ACCESSIBILITY_STYLE_FILE
    accessibility_script_path = ui_dir / ACCESSIBILITY_SCRIPT_FILE

    html = _read_required(index_path, "UI HTML")
    css = _read_required(style_path, "UI stylesheet")
    javascript = _read_required(app_path, "UI application")
    accessibility_css = _read_required(
        accessibility_style_path,
        "UI accessibility stylesheet",
    )
    accessibility_javascript = _read_required(
        accessibility_script_path,
        "UI accessibility application",
    )

    _require_exactly_once(html, STYLE_LINK, "stylesheet reference")
    _require_exactly_once(html, WEEKLY_BRIDGE_TAG, "weekly bridge reference")
    _require_exactly_once(html, SCRIPT_TAG, "application reference")
    _require_exactly_once(html, "</head>", "HTML head closing tag")
    _require_markers(html, _REQUIRED_HTML_MARKERS, "UI HTML")
    _require_markers(css, _REQUIRED_CSS_MARKERS, "UI stylesheet")
    _require_markers(javascript, _REQUIRED_JS_MARKERS, "UI application")
    _require_exactly_once(
        accessibility_css,
        ACCESSIBILITY_MARKER,
        "UI accessibility stylesheet marker",
    )
    _require_exactly_once(
        accessibility_javascript,
        ACCESSIBILITY_MARKER,
        "UI accessibility application marker",
    )
    _require_exactly_once(css, LEGACY_GLOBAL_ZOOM, "legacy global zoom workaround")

    # W6 removes the production dependency on CSS zoom. Keep the old source
    # layer reviewable until the later W5 cascade-consolidation gate, but never
    # emit the workaround into a release artifact.
    css = css.replace(LEGACY_GLOBAL_ZOOM, "", 1)
    css = f"{css.rstrip()}\n\n{accessibility_css.rstrip()}"
    javascript = f"{javascript.rstrip()}\n\n{accessibility_javascript.rstrip()}"

    if "</style" in css.lower():
        raise UiBundleError("UI stylesheet contains an unsafe </style sequence")
    if "</script" in javascript.lower():
        raise UiBundleError("UI application contains an unsafe </script sequence")
    if PRODUCTION_META in html or STYLE_MARKER in html or SCRIPT_MARKER in html:
        raise UiBundleError("UI HTML is already production-bundled")

    bundled_style = (
        f'<style {STYLE_MARKER}>\n'
        f"{css.rstrip()}\n"
        "</style>"
    )
    bundled_script = (
        f'<script {SCRIPT_MARKER}>\n'
        f"{javascript.rstrip()}\n"
        "</script>"
    )

    bundled = html.replace(STYLE_LINK, bundled_style, 1)
    bundled = bundled.replace(WEEKLY_BRIDGE_TAG, "", 1)
    bundled = bundled.replace(SCRIPT_TAG, bundled_script, 1)
    bundled = bundled.replace(
        "</head>",
        f"  {PRODUCTION_META}\n</head>",
        1,
    )
    if not bundled.endswith("\n"):
        bundled += "\n"

    for forbidden in (STYLE_LINK, WEEKLY_BRIDGE_TAG, SCRIPT_TAG, LEGACY_GLOBAL_ZOOM):
        if forbidden in bundled:
            raise UiBundleError(f"production UI retained forbidden source contract: {forbidden}")
    _require_exactly_once(bundled, PRODUCTION_META, "production bundle marker")
    _require_exactly_once(bundled, STYLE_MARKER, "bundled stylesheet marker")
    _require_exactly_once(bundled, SCRIPT_MARKER, "bundled application marker")
    if bundled.count(ACCESSIBILITY_MARKER) != 2:
        raise UiBundleError("production UI must contain both W6 accessibility patch markers")
    _require_markers(bundled, _REQUIRED_HTML_MARKERS, "production UI")
    _require_markers(bundled, _REQUIRED_CSS_MARKERS, "production UI stylesheet")
    _require_markers(bundled, _REQUIRED_JS_MARKERS, "production UI application")

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=ui_dir,
        prefix=".index.production.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)
        handle.write(bundled)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary_path, index_path.stat().st_mode & 0o777)
        os.replace(temporary_path, index_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    payload = index_path.read_bytes()
    print("PRODUCTION_UI_BUNDLE=PASS")
    print(f"PRODUCTION_UI_BYTES={len(payload)}")
    print(f"PRODUCTION_UI_SHA256={sha256(payload).hexdigest()}")
    return index_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the immutable self-contained Hermes Deals production UI",
    )
    parser.add_argument(
        "--ui-dir",
        type=Path,
        required=True,
        help="Directory containing index.html, styles.css, and verified W3 app.js",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        build_production_ui_bundle(args.ui_dir)
    except (OSError, UiBundleError) as exc:
        raise SystemExit(f"PRODUCTION_UI_BUNDLE=FAIL: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
