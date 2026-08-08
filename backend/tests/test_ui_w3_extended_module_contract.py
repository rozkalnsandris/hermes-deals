from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "backend" / "frontend"
UI_APP = ROOT / "backend" / "app" / "ui" / "app.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_w3_catalog_module_preserves_canonical_trust_and_request_contracts() -> None:
    entry = read(FRONTEND / "src" / "app.js")
    catalog = read(FRONTEND / "src" / "features" / "catalog.js")
    legacy = read(UI_APP)

    assert 'from "./features/catalog.js"' in entry
    assert "export function initCatalog" in catalog
    assert "/api/v1/catalog" in catalog
    for marker in (
        "/api/v1/canonical-products/",
        "/current-offers?as_of=",
        "/price-history?limit=60",
        "Salīdzinājums tiek rādīts tikai apstiprinātai canonical produkta identitātei",
        "Canonical produkts",
        "Cenu vēsture",
    ):
        assert marker in catalog
        assert marker in legacy


def test_w3_navigation_module_preserves_public_url_state_contract() -> None:
    entry = read(FRONTEND / "src" / "app.js")
    navigation = read(FRONTEND / "src" / "ui" / "navigation.js")
    legacy = read(UI_APP)

    assert 'from "./ui/navigation.js"' in entry
    assert "export function viewQuery" in navigation
    assert "export function parseViewQuery" in navigation
    for marker in (
        'params.set("mode"',
        'params.set("date"',
        'params.set("q"',
        'params.set("retailer"',
        'params.set("sort"',
        'params.set("view"',
        'params.set("current"',
        'params.set("comparison"',
    ):
        assert marker in navigation
    for query_name in ("mode", "date", "q", "retailer", "sort", "view", "current", "comparison"):
        assert f'p.set("{query_name}"' in legacy or f'p.has("{query_name}"' in legacy


def test_w3_overlay_module_preserves_lock_and_focus_return_contract() -> None:
    entry = read(FRONTEND / "src" / "app.js")
    overlays = read(FRONTEND / "src" / "ui" / "overlays.js")
    legacy = read(UI_APP)

    assert 'from "./ui/overlays.js"' in entry
    assert "export function initOverlays" in overlays
    for marker in (
        'document.body.classList.add("locked")',
        'document.body.classList.remove("locked")',
        'clearListConfirm.setAttribute("aria-hidden", "false")',
        'clearListConfirm.setAttribute("aria-hidden", "true")',
        "clearListReturnFocus",
        'event.key !== "Tab"',
    ):
        assert marker in overlays
    assert 'document.body.classList.add("locked")' in legacy
    assert 'document.body.classList.remove("locked")' in legacy
    assert "clearListReturnFocus" in legacy


def test_w3_review_refresh_module_preserves_cross_page_refresh_transport() -> None:
    entry = read(FRONTEND / "src" / "app.js")
    review = read(FRONTEND / "src" / "ui" / "review-refresh.js")
    legacy = read(UI_APP)

    assert 'from "./ui/review-refresh.js"' in entry
    assert 'REVIEW_REFRESH_CHANNEL = "hermes-deals-review"' in review
    assert "REVIEW_REFRESH_DELAY_MS = 180" in review
    assert 'event.data?.type === "review-published"' in review
    assert "REVIEW_REFRESH_KEY" in review
    assert 'documentObject.addEventListener("visibilitychange"' in review
    for marker in (
        "hermes-deals-review",
        "review-published",
        "REVIEW_REFRESH_KEY",
        "visibilitychange",
    ):
        assert marker in legacy


def test_w3_node_tests_cover_catalog_navigation_and_shopping_boundaries() -> None:
    catalog_tests = read(FRONTEND / "tests" / "catalog.test.mjs")
    navigation_tests = read(FRONTEND / "tests" / "navigation.test.mjs")
    shopping_tests = read(FRONTEND / "tests" / "shopping-list.test.mjs")

    assert "canonical URL preserves filter and sort contract" in catalog_tests
    assert "canonical detail performs the same three endpoint requests" in catalog_tests
    assert "view query preserves public URL parameter names and order" in navigation_tests
    assert "review refresh transport constants remain stable" in navigation_tests
    assert "canonical basket payload excludes completed and retailer-deal rows" in shopping_tests
