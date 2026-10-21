from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JAVASCRIPT = ROOT / "backend" / "app" / "north_star" / "static" / "north-star.js"
INDEX = ROOT / "backend" / "app" / "north_star" / "templates" / "index.html"


def test_mobile_drawer_uses_modal_semantics_without_inerting_its_ancestor() -> None:
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    assert '<aside class="sidebar" id="sidebar" aria-label="Galvenā izvēlne">' in index
    assert "node.setAttribute('role', 'dialog')" in javascript
    assert "node.setAttribute('aria-modal', 'true')" in javascript
    assert "node.removeAttribute('role')" in javascript
    assert "node.removeAttribute('aria-modal')" in javascript

    # Drawer background becomes unavailable to keyboard and accessibility-tree
    # navigation while the sidebar remains outside any inert ancestor.
    assert "document.querySelector('.skip-link').inert = backgroundInert" in javascript
    assert "document.querySelector('.workspace').inert = backgroundInert" in javascript
    assert "document.querySelector('.mobile-bottom').inert = backgroundInert" in javascript
    assert "document.querySelector('.app-layout').inert = detailOpen" in javascript
    assert "document.querySelector('.app-layout').inert = backgroundInert" not in javascript


def test_drawer_escape_tab_resize_and_htmx_paths_restore_accessibility_state() -> None:
    javascript = JAVASCRIPT.read_text(encoding="utf-8")

    assert "const menuOpen = mobile.matches && document.body.classList.contains('sidebar-open')" in javascript
    assert "else if (menuOpen) menu(false)" in javascript
    assert "const container = detail || (menuOpen ? sidebar() : null)" in javascript
    assert "event.key !== 'Tab'" in javascript
    assert "event.shiftKey" in javascript
    assert "returnTarget?.isConnected && returnTarget.getClientRects().length" in javascript

    # Crossing to desktop clears modal state instead of leaving an inert page
    # or a focus trap. Entering mobile moves focus out of a sidebar that is
    # about to become inert while closed.
    assert "if (!mobile.matches)" in javascript
    assert "document.body.classList.remove('sidebar-open')" in javascript
    assert "sidebar().contains(document.activeElement)" in javascript
    assert "document.querySelector('[data-menu-open]')?.focus()" in javascript
    assert "syncOverlayState()" in javascript

    # HTMX navigation rebuilds the swapped page and clears drawer state.
    assert "if (event.detail.target.id === 'home-content') initialize(true)" in javascript


def test_product_dialog_keeps_its_modal_regression_contract() -> None:
    javascript = JAVASCRIPT.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    assert 'class="product-dialog" role="dialog" aria-modal="true"' in index
    assert "document.querySelector('.app-layout').inert = detailOpen" in javascript
    assert "document.querySelector('.mobile-bottom').inert = backgroundInert" in javascript
    assert "if (detail) detail.focus()" in javascript
    assert "if (detail) detail.querySelector('[data-dialog-close]').click()" in javascript
