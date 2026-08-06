#!/usr/bin/env python3
"""One-time branch-local branding patch for issue #217."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
INDEX = ROOT / "backend/app/ui/index.html"
REVIEW = ROOT / "backend/app/ui/review.html"
STYLES = ROOT / "backend/app/ui/styles.css"
MAIN = ROOT / "backend/app/main.py"
ASSETS = ROOT / "backend/app/ui/assets"


ASSETS.mkdir(parents=True, exist_ok=True)
logo = ASSETS / "deals-logo.svg"
favicon = ASSETS / "deals-favicon.svg"
if not logo.exists():
    raise SystemExit("missing deals-logo.svg")
favicon.write_text(logo.read_text(encoding="utf-8"), encoding="utf-8")

readme_block = """<p align="center">
  <img src="backend/app/ui/assets/deals-logo.svg" alt="Hermes Deals logo" width="160">
</p>

"""
text = README.read_text(encoding="utf-8")
if "backend/app/ui/assets/deals-logo.svg" not in text:
    README.write_text(readme_block + text, encoding="utf-8")

text = INDEX.read_text(encoding="utf-8")
favicon_link = '  <link rel="icon" type="image/svg+xml" href="/ui/assets/deals-favicon.svg">\n'
if "/ui/assets/deals-favicon.svg" not in text:
    marker = '  <meta name="hermes-ui-fix" content="weekly-overview-v1">\n'
    if marker not in text:
        raise SystemExit("index favicon insertion marker missing")
    text = text.replace(marker, favicon_link + marker, 1)
logo_img = '<img class="brand-logo" src="/ui/assets/deals-logo.svg" alt="">'
if logo_img not in text:
    marker = '<svg class="brand-leaf"'
    count = text.count(marker)
    if count < 2:
        raise SystemExit(f"expected at least two brand-leaf markers, found {count}")
    text = text.replace(marker, logo_img + marker)
weekly_img = '<img class="weekly-brand-mark weekly-brand-logo" src="/ui/assets/deals-logo.svg" alt="">'
if weekly_img not in text:
    marker = '<svg class="weekly-brand-mark"'
    if marker not in text:
        raise SystemExit("weekly brand marker missing")
    text = text.replace(marker, weekly_img + marker, 1)
INDEX.write_text(text, encoding="utf-8")

text = REVIEW.read_text(encoding="utf-8")
if "/ui/assets/deals-favicon.svg" not in text:
    marker = "  <title>Hermes Deals — Pārskatīšana</title>\n"
    if marker not in text:
        raise SystemExit("review favicon insertion marker missing")
    text = text.replace(marker, favicon_link + marker, 1)
review_img = '  <img class="review-brand-logo" src="/ui/assets/deals-logo.svg" alt="Hermes Deals logo">\n'
if 'class="review-brand-logo"' not in text:
    marker = "<header>\n"
    if marker not in text:
        raise SystemExit("review header marker missing")
    text = text.replace(marker, marker + review_img, 1)
review_css = '    .review-brand-logo{float:left;width:52px;height:52px;object-fit:contain;margin:0 12px 6px 0}header::after{content:"";display:block;clear:both}\n'
if ".review-brand-logo{" not in text:
    marker = '    h1{font-size:22px;margin:0 0 4px}.muted{color:#686d74}\n'
    if marker not in text:
        raise SystemExit("review CSS marker missing")
    text = text.replace(marker, marker + review_css, 1)
REVIEW.write_text(text, encoding="utf-8")

css = STYLES.read_text(encoding="utf-8")
branding_css = """

/* Hermes Deals project branding (#217). */
.brand-logo{width:34px;height:34px;flex:0 0 34px;object-fit:contain}
svg.brand-leaf{display:none}
.weekly-brand-logo{width:34px;height:34px;flex:0 0 34px;object-fit:contain}
svg.weekly-brand-mark{display:none}
@media(max-width:560px){.brand-logo,.weekly-brand-logo{width:30px;height:30px;flex-basis:30px}}
"""
if "Hermes Deals project branding (#217)" not in css:
    STYLES.write_text(css.rstrip() + branding_css + "\n", encoding="utf-8")

source = MAIN.read_text(encoding="utf-8")
if "UI_BRANDING_ASSETS" not in source:
    marker = 'UI_APP_PATH = UI_DIR / "app.js"\n'
    addition = '''UI_ASSETS_DIR = UI_DIR / "assets"
UI_BRANDING_ASSETS = {
    "deals-logo.svg": UI_ASSETS_DIR / "deals-logo.svg",
    "deals-favicon.svg": UI_ASSETS_DIR / "deals-favicon.svg",
}
'''
    if marker not in source:
        raise SystemExit("main.py asset constant marker missing")
    source = source.replace(marker, marker + addition, 1)
if "def family_ui_asset(" not in source:
    marker = '''@app.get("/ui/app.js", include_in_schema=False)
def family_ui_app() -> FileResponse:
    if not UI_APP_PATH.exists():
        raise HTTPException(status_code=503, detail="UI application bundle is not available")
    return FileResponse(UI_APP_PATH, media_type="application/javascript")
'''
    route = '''

@app.get("/ui/assets/{asset_name}", include_in_schema=False)
def family_ui_asset(asset_name: str) -> FileResponse:
    asset_path = UI_BRANDING_ASSETS.get(asset_name)
    if asset_path is None:
        raise HTTPException(status_code=404, detail="UI asset is not available")
    if not asset_path.exists():
        raise HTTPException(status_code=503, detail="UI asset is not available")
    return FileResponse(asset_path, media_type="image/svg+xml")
'''
    if marker not in source:
        raise SystemExit("main.py route insertion marker missing")
    source = source.replace(marker, marker + route, 1)
MAIN.write_text(source, encoding="utf-8")

tests = ROOT / "backend/tests/test_ui_branding.py"
tests.write_text(
    '''from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


UI_DIR = Path(__file__).resolve().parents[1] / "app" / "ui"


def test_deals_branding_is_referenced_by_both_ui_documents() -> None:
    index = (UI_DIR / "index.html").read_text(encoding="utf-8")
    review = (UI_DIR / "review.html").read_text(encoding="utf-8")
    assert "/ui/assets/deals-logo.svg" in index
    assert "/ui/assets/deals-favicon.svg" in index
    assert "/ui/assets/deals-logo.svg" in review
    assert "/ui/assets/deals-favicon.svg" in review
    assert (UI_DIR / "assets" / "deals-logo.svg").is_file()
    assert (UI_DIR / "assets" / "deals-favicon.svg").is_file()


def test_deals_branding_routes_are_explicit_and_fail_closed() -> None:
    client = TestClient(app)
    for asset_name in ("deals-logo.svg", "deals-favicon.svg"):
        response = client.get(f"/ui/assets/{asset_name}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert response.content.startswith(b"<svg")
    assert client.get("/ui/assets/not-allowed.svg").status_code == 404
''',
    encoding="utf-8",
)
