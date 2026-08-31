from __future__ import annotations

from pathlib import Path
import shutil

from backend.app.ui_bundle import (
    ACCESSIBILITY_MARKER,
    LEGACY_GLOBAL_ZOOM,
    build_production_ui_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "backend" / "app" / "ui"
CSS_FIX = UI / "accessibility-fixes.css"
JS_FIX = UI / "accessibility-fixes.js"


def test_mobile_navigation_matches_five_real_actions_without_overflow_contract() -> None:
    css = CSS_FIX.read_text(encoding="utf-8")
    assert "repeat(5,minmax(0,1fr))" in css
    assert "max-width:100%" in css
    assert "min-width:0" in css
    assert "overflow:hidden" in css


def test_closed_drawer_and_details_are_inert_with_dialog_focus_lifecycle() -> None:
    javascript = JS_FIX.read_text(encoding="utf-8")
    assert 'node.setAttribute("inert", "")' in javascript
    assert 'node.removeAttribute("inert")' in javascript
    assert 'node.setAttribute("aria-hidden", "true")' in javascript
    assert 'node.setAttribute("aria-hidden", "false")' in javascript
    assert 'node.setAttribute("role", "dialog")' in javascript
    assert 'node.setAttribute("aria-modal", "true")' in javascript
    assert "returnFocus.set(node, active)" in javascript
    assert "target.focus({ preventScroll: true })" in javascript
    assert 'event.key !== "Tab"' in javascript
    assert "activeOverlay.contains(document.activeElement)" in javascript


def test_visible_focus_and_reduced_motion_cover_primary_interactions() -> None:
    css = CSS_FIX.read_text(encoding="utf-8")
    javascript = JS_FIX.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline:3px solid var(--accent)" in css
    assert "prefers-reduced-motion:reduce" in css
    assert "transition-duration:.01ms!important" in css
    assert "animation-duration:.01ms!important" in css
    assert "scroll-behavior:auto!important" in css
    assert 'options.behavior === "smooth"' in javascript
    assert 'behavior: "auto"' in javascript


def _prepare_w3_fixture(target: Path) -> None:
    """Mirror the deterministic W3 build contract that Docker stages before bundling."""
    app_path = target / "app.js"
    app_path.write_text(
        """const identity = "HERMES_UI_SCRIPT_OPEN:";
const bootstrap = "w3-behavior-preserving-bootstrap-v1";
const weekly = "normalized_unique_deals_by_id_v1";
const current = "/api/v1/deals/current";
const daily = "/api/v1/deals/daily-specials";
const dailyContract = "explicit_immutable_retailer_evidence_only";
const catalog = "/api/v1/catalog";
void [identity, bootstrap, weekly, current, daily, dailyContract, catalog];
""",
        encoding="utf-8",
    )


def test_production_bundle_removes_global_zoom_and_includes_w6_contract(tmp_path: Path) -> None:
    target = tmp_path / "ui"
    shutil.copytree(UI, target)
    _prepare_w3_fixture(target)
    output = build_production_ui_bundle(target)
    bundled = output.read_text(encoding="utf-8")

    assert LEGACY_GLOBAL_ZOOM not in bundled
    assert bundled.count(ACCESSIBILITY_MARKER) == 2
    assert "repeat(5,minmax(0,1fr))" in bundled
    assert 'node.setAttribute("inert", "")' in bundled
    assert 'node.setAttribute("role", "dialog")' in bundled
    assert ":focus-visible" in bundled
    assert "prefers-reduced-motion:reduce" in bundled
