"""Source-level contract for the one-image viewer; runtime behavior needs mobile canary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "backend/app/north_star/static/north-star.js").read_text(encoding="utf-8")
CSS = (ROOT / "backend/app/north_star/static/modern.css").read_text(encoding="utf-8")
INDEX = (ROOT / "backend/app/north_star/templates/index.html").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "backend/app/north_star/templates/booklets.html").read_text(encoding="utf-8")


def test_immersive_viewer_does_not_obscure_booklet_with_original_controls():
    assert ".booklet-reader.booklet-viewer-open .booklet-controls," in CSS
    assert "data-booklet-fullscreen" not in TEMPLATE
    assert "booklet-swipe-hint" not in TEMPLATE
    assert "Ja attēls neielādējas" not in TEMPLATE
    assert ".booklet-reader.booklet-viewer-open .booklet-canvas {" in CSS
    assert "touch-action:none" in CSS
    assert "data-booklet-viewer-hud" in TEMPLATE
    assert "data-booklet-viewer-close" in TEMPLATE
    assert "data-booklet-viewer-count" in TEMPLATE
    assert 'data-booklet-image src="{{ booklet.image_url }}"' in TEMPLATE
    assert 'class="booklet-slide"' not in TEMPLATE


def test_user_gestures_keep_single_verified_image_and_zoom_at_focal_point():
    assert "image.addEventListener('click', () => { if (!isOpen()) open(); });" in JS
    assert "if (!isOpen()) { open(); return; }" not in JS
    assert "requestFullscreen({ navigationUI: 'hide' })" in JS
    assert "canvas.addEventListener('touchmove'" in JS
    assert "event.touches.length >= 2" in JS
    assert "anchorX" in JS and "anchorY" in JS
    assert "event.preventDefault();" in JS
    assert "if (scale <= 1.01) navigate(" in JS
    assert "lastTouch < 700" not in JS
    assert "zoomAt(2.5, event.clientX, event.clientY)" not in JS
    assert "scale = 1" in JS and "resetZoom()" in JS
    assert "image.src = options[number - 1].dataset.bookletImageUrl" in JS
    assert "netto-viewer-v7" in INDEX


def test_separate_zoom_keeps_product_click_unbound():
    assert "image.addEventListener('click', () => { if (!isOpen()) open(); });" in JS
    assert "image.addEventListener('click', event => {" not in JS
    assert "data-booklet-zoom-in" in TEMPLATE and "data-booklet-zoom-out" in TEMPLATE
    assert "data-booklet-zoom-level" in TEMPLATE
    assert "zoomIn.addEventListener('click'" in JS
    assert "zoomOut.addEventListener('click'" in JS
    assert "canvas.addEventListener('wheel'" in JS
    assert "event.deltaMode === 1" in JS
    assert "event.cancelable" in JS and "passive:false" in JS
    assert "event.clientX, event.clientY" in JS
    assert "event.pointerType !== 'mouse'" in JS
    assert "canvas.addEventListener('pointermove'" in JS
    assert "scale > 1.01 ? 'pan' : 'swipe'" in JS
    assert ".booklet-reader.booklet-viewer-open .booklet-canvas.is-zoomed { cursor:grab; }" in CSS


def test_zoom_resolution_uses_only_verified_data_and_falls_back_on_asset_failure():
    assert "option.dataset.bookletZoomImageUrl" in JS
    assert "failedHiResPages = new Set()" in JS
    assert "image.addEventListener('error'" in JS
    assert "image.src = option.dataset.bookletImageUrl" in JS
    assert "scale > 1.01" in JS
    assert 'data-booklet-zoom-image-url="{{ p.zoom_image_url }}"' in TEMPLATE
    assert "netto-viewer-v7" in INDEX


def test_fullscreen_booklet_image_rerasterizes_when_scaled():
    image_rules = CSS.split(
        ".booklet-reader.booklet-viewer-open .booklet-page-image {", 1
    )[1].split("}", 1)[0]
    assert "will-change" not in image_rules
    assert "transform-origin:center center" in image_rules
    assert "object-fit:contain" in image_rules
    assert "netto-viewer-v7" in INDEX


def test_inline_booklet_navigation_highlights_only_enabled_pages():
    # The bug was CSS [aria-disabled], which also matches "false".
    assert '.booklet-controls [aria-disabled="true"]' in CSS
    assert '.booklet-controls [aria-disabled] {' not in CSS
    assert '[data-booklet-prev]:not([aria-disabled="true"])' in CSS
    assert '[data-booklet-next]:not([aria-disabled="true"])' in CSS
    assert "if (disabled) link.setAttribute('aria-disabled', 'true');" in JS
    assert "else link.removeAttribute('aria-disabled');" in JS
    assert 'link.tabIndex = disabled ? -1 : 0' in JS
    assert 'number === 1' in JS and 'number === options.length' in JS


def test_cover_and_keyboard_still_open_reader_without_fullscreen_button():
    assert 'role="button" aria-expanded="false" data-booklet-swipe=' in TEMPLATE
    assert "canvas.setAttribute('aria-expanded', 'true');" in JS
    assert "canvas.setAttribute('aria-expanded', 'false');" in JS
    assert "canvas.focus({ preventScroll:true });" in JS
    assert "image.addEventListener('click', () => { if (!isOpen()) open(); });" in JS
    assert "if (!isOpen() && (event.key === 'Enter' || event.key === ' '))" in JS
    assert "data-booklet-fullscreen" not in JS
