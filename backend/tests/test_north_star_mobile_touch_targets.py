from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "backend" / "app" / "north_star" / "static" / "modern.css"
COMPONENTS = ROOT / "backend" / "app" / "north_star" / "templates" / "components.html"
INDEX = ROOT / "backend" / "app" / "north_star" / "templates" / "index.html"
JAVASCRIPT = ROOT / "backend" / "app" / "north_star" / "static" / "north-star.js"


def test_mobile_primary_touch_targets_are_at_least_44px_at_412_and_320() -> None:
    css = CSS.read_text(encoding="utf-8")
    mobile_start = css.index("@media (max-width:760px) {")
    narrow_start = css.index("@media (max-width:380px) {", mobile_start)
    mobile = css[mobile_start:narrow_start]
    narrow = css[narrow_start:css.index("@media (prefers-reduced-motion: reduce)", narrow_start)]

    assert ".week-picker .week-arrow { width: 44px; height: 44px; }" in mobile
    assert ".offer-add { width: 44px; min-height: 44px; }" in mobile
    assert ".offer-favorite .icon-button { min-width: 44px; min-height: 44px; }" in mobile
    assert ".shopping-row .check-button { width: 44px; min-width: 44px; height: 44px; min-height: 44px; }" in mobile
    assert ".shopping-row .remove-button { min-width: 44px; min-height: 44px; }" in mobile

    # The 320px override must not shrink the week controls again.
    assert ".week-picker .week-arrow { width: 44px; height: 44px; }" in narrow

    # Existing narrow-layout safeguards keep the enlarged targets from forcing
    # a two-column card layout or a fixed-width week label.
    assert "grid-template-columns: 1fr" in narrow
    assert ".week-picker, .week-picker > span { min-width: 0; }" in css


def test_touch_targets_keep_focus_names_and_single_server_post_forms() -> None:
    css = CSS.read_text(encoding="utf-8")
    components = COMPONENTS.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    javascript = JAVASCRIPT.read_text(encoding="utf-8")

    assert ":focus-visible" in css

    assert 'aria-label="{% if p.favorite %}Noņemt no favorītiem{% else %}Saglabāt favorītos{% endif %}: {{ p.name }}"' in components
    assert 'aria-label="Pievienot sarakstam: {{ p.name }}"' in components
    assert 'aria-label="{% if row.checked %}Atzīmēt kā nenopirktu{% else %}Atzīmēt kā nopirktu{% endif %}: {{ row.name }}"' in components
    assert 'aria-label="Noņemt no saraksta: {{ row.name }}"' in components
    assert 'aria-label="Iepriekšējā nedēļa"' in index
    assert 'aria-label="Nākamā nedēļa"' in index

    # Each write stays an ordinary, non-boosted server form. The browser
    # fallback explicitly refuses POST retries, so enlarging a button cannot
    # introduce a second client-side write path.
    for action in ("favorite", "add", "toggle", "remove"):
        assert f'/actions/{action}" method="post" hx-boost="false"' in components
    assert "if (config?.verb !== 'get') return;" in javascript
    assert "POST forms are deliberately not boosted" in javascript
