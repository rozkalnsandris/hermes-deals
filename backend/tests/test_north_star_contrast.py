from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
MODERN_CSS = ROOT / "backend" / "app" / "north_star" / "static" / "modern.css"
INDEX = ROOT / "backend" / "app" / "north_star" / "templates" / "index.html"
COMPONENTS = ROOT / "backend" / "app" / "north_star" / "templates" / "components.html"

# Visible normal-size text audited in #1037. Hidden sr-only text, focus outlines,
# disabled-state opacity, and aria-hidden/decorative graphics are intentionally
# outside the WCAG 1.4.3 text-contrast scan.
AUDITED = {
    ".empty-state": "#ffffff",
    ".offer-bottom del": "#ffffff",
    ".page-footer": "#f5f7fb",
    ".eyebrow": "#f5f7fb",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _luminance(value: str) -> float:
    channels = []
    for channel in _hex_to_rgb(value):
        scaled = channel / 255
        channels.append(scaled / 12.92 if scaled <= 0.04045 else ((scaled + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _declared_color(css: str, selector: str) -> str:
    matches = re.findall(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]+)\}}", css)
    assert matches, f"missing explicit modern override for {selector}"
    colors = []
    for rule in matches:
        color = re.search(r"(?:^|;)\s*color:\s*([^;]+)", rule)
        if color:
            colors.append(color.group(1).strip())
    assert colors, f"missing explicit color declaration for {selector}"
    return colors[-1]


def _muted(css: str) -> str:
    match = re.search(r"--muted:\s*(#[0-9a-fA-F]{6})", css)
    assert match
    return match.group(1)


def test_audited_visible_text_meets_wcag_aa_on_desktop_and_mobile() -> None:
    css = MODERN_CSS.read_text(encoding="utf-8")
    foreground = _muted(css)

    # modern.css loads after north-star.css, so these explicit rules own the
    # audited cascade. Mobile rules change size/layout only, not these colors.
    for selector, background in AUDITED.items():
        assert _declared_color(css, selector) == "var(--muted)"
        ratio = _contrast(foreground, background)
        assert ratio >= 4.5, f"{selector}: {ratio:.3f}:1"

    mobile = css[css.index("@media (max-width:760px)"):]
    assert ".eyebrow { font-size: .6875rem; }" in mobile
    assert ".page-footer { font-size: .75rem; flex-direction: column; gap: 5px; }" in mobile


def test_contrast_scan_targets_rendered_empty_favorites_offers_and_footer_text() -> None:
    index = INDEX.read_text(encoding="utf-8")
    components = COMPONENTS.read_text(encoding="utf-8")

    assert 'class="eyebrow"' in index
    assert 'class="page-footer"' in index
    assert "view in ['deals','favorites']" in index
    assert 'class="empty-state' in components
    assert "<del>" in components

    # Classification guard: do not accidentally turn hidden/non-text states
    # into 1.4.3 text targets when the audited list changes.
    assert ".sr-only" not in AUDITED
    assert ":focus-visible" not in AUDITED
    assert "button:disabled" not in AUDITED
