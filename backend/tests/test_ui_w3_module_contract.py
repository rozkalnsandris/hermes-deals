from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
UI = ROOT / "backend" / "app" / "ui"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_w3_build_contract_is_pinned_and_framework_free() -> None:
    package = json.loads(read(FRONTEND / "package.json"))
    assert package["private"] is True
    assert package["type"] == "module"
    assert package["engines"] == {"node": ">=22.12.0"}
    assert package["devDependencies"] == {"vite": "8.1.5"}
    assert package["scripts"] == {
        "test": "node --test tests/*.test.mjs",
        "build": "node node_modules/vite/bin/vite.js build --config vite.config.js",
        "build:check": "node node_modules/vite/bin/vite.js build --config vite.config.js && node scripts/verify-build.mjs",
    }
    assert read(FRONTEND / ".nvmrc") == "24.18.0\n"
    forbidden = {"react", "react-dom", "vue", "svelte", "@angular/core"}
    declared = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
    assert forbidden.isdisjoint(declared)


def test_w3_vite_output_is_one_readable_non_sourcemapped_module() -> None:
    config = read(FRONTEND / "vite.config.js")
    assert 'entry: resolve(root, "src/app.js")' in config
    assert 'formats: ["es"]' in config
    assert 'fileName: () => "app.js"' in config
    assert 'entryFileNames: "app.js"' in config
    assert "rolldownOptions" in config
    assert "codeSplitting: false" in config
    assert "rollupOptions" not in config
    assert "inlineDynamicImports" not in config
    assert "sourcemap: false" in config
    assert "minify: false" in config
    assert "react" not in config.lower()
    assert "vue" not in config.lower()


def test_w3_core_modules_pin_existing_browser_contracts() -> None:
    app = read(FRONTEND / "src" / "app.js")
    api = read(FRONTEND / "src" / "core" / "api.js")
    dates = read(FRONTEND / "src" / "core" / "dates.js")
    dom = read(FRONTEND / "src" / "core" / "dom.js")
    storage = read(FRONTEND / "src" / "core" / "storage.js")
    assert 'from "./core/api.js"' in app
    assert 'from "./core/dates.js"' in app
    assert 'from "./core/dom.js"' in app
    assert 'from "./core/storage.js"' in app
    for key in (
        "hermesDeals.shoppingList.v1",
        "hermesDeals.uiPreferences.v4",
        "hermesDeals.viewPreferences.v5",
        "hermesDeals.filterPanel.v1",
        "hermesDealsReviewRefresh",
    ):
        assert key in storage
        assert key in read(UI / "app.js")
    assert 'timeZone: BERLIN_TIME_ZONE' in dates
    assert 'const BERLIN_TIME_ZONE = "Europe/Berlin"' in dates
    assert 'export function fmtDate' in dates
    assert 'export function parseLvDate' in dates
    assert "export class UiApiError" in api
    assert "export async function fetchJson" in api
    assert 'response.headers.get("cf-ray")' in api
    assert "export function esc" in dom
    assert '["http:", "https:"]' in dom


def test_w3_current_deals_module_preserves_request_render_and_controller_contracts() -> None:
    app = read(FRONTEND / "src" / "app.js")
    deals = read(FRONTEND / "src" / "features" / "deals.js")
    legacy = read(UI / "app.js")
    assert 'from "./features/deals.js"' in app
    assert "export const PAGE_SIZE = 12" in deals
    assert "export function initCurrentDeals" in deals
    assert "/api/v1/deals/current" in deals
    assert 'view: dealView === "upcoming" ? "upcoming" : "current"' in deals
    for marker in ("app_only", "coupon_only", "discount_only", "image_only"):
        assert marker in deals
        assert marker in legacy
    for marker in ("unit_price_only", "example_total_plus_unit", "app_example_total_plus_unit"):
        assert marker in deals
        assert marker in legacy
    assert "export function paginationItems" in deals
    assert "export function rawDealCard" in deals
    assert "export function dealPageSummary" in deals
    for text in (
        "Dati īslaicīgi nav pieejami",
        "Šim filtram nav drīzumā gaidāmu piedāvājumu.",
        "Šim filtram nav aktuālu piedāvājumu.",
    ):
        assert text in deals
        assert text in legacy


def test_w3_daily_special_module_preserves_explicit_evidence_contract() -> None:
    app = read(FRONTEND / "src" / "app.js")
    daily = read(FRONTEND / "src" / "features" / "daily-specials.js")
    legacy = read(UI / "app.js")
    assert 'from "./features/daily-specials.js"' in app
    assert "export function initDailySpecials" in daily
    assert 'DAILY_SPECIAL_SOURCE_CONTRACT = "explicit_immutable_retailer_evidence_only"' in daily
    assert "/api/v1/deals/daily-specials" in daily
    assert "payload.source_contract !== DAILY_SPECIAL_SOURCE_CONTRACT" in daily
    assert 'deal.special_confidence === "high"' in daily
    assert 'deal.special_valid_on === iso' in daily
    assert "legacyCurrentDealDailySpecialContract" in daily
    assert "/api/v1/deals/current" in daily
    assert "DAILY_SPECIAL_MAX_PAGES = 20" in daily
    assert "return false" in daily
    for marker in (
        "explicit_immutable_retailer_evidence_only",
        "legacyCurrentDealDailySpecialContract",
        "Šodienas īpašās akcijas neizdevās ielādēt.",
        "Rītdienas īpašās akcijas neizdevās ielādēt.",
    ):
        assert marker in legacy
        assert marker in daily
    assert "DAILY_SPECIAL_MAX_PAGES=20" in legacy


def test_w3_shopping_list_module_preserves_storage_and_basket_contracts() -> None:
    app = read(FRONTEND / "src" / "app.js")
    shopping = read(FRONTEND / "src" / "features" / "shopping-list.js")
    legacy = read(UI / "app.js")
    assert 'from "./features/shopping-list.js"' in app
    assert "export function initShoppingList" in shopping
    assert "STORAGE_KEY" in shopping
    assert "normalizeListItem" in shopping
    assert "Math.max(1, Math.min(99" in shopping
    assert ".slice(0, 160)" in shopping
    assert "/api/v1/ui/basket/compare" in shopping
    assert "canonical_product_id" in shopping
    assert "Konkrēts veikala piedāvājums" in shopping
    assert "Canonical produkts" in shopping
    for marker in (
        "hermesDeals.shoppingList.v1",
        "/api/v1/ui/basket/compare",
        "canonical_product_id",
        "Konkrēts veikala piedāvājums",
        "Canonical produkts",
    ):
        assert marker in legacy


def test_w3_node_feature_tests_exist_for_request_trust_and_storage_parity() -> None:
    feature_tests = read(FRONTEND / "tests" / "features.test.mjs")
    shopping_tests = read(FRONTEND / "tests" / "shopping-list.test.mjs")
    assert "current deals URL preserves query contract" in feature_tests
    assert "daily-special initial data performs exactly two explicit requests" in feature_tests
    assert "explicit daily-special endpoint filters fail-closed evidence" in feature_tests
    assert "legacy daily-special helper remains bounded and deduplicated" in feature_tests
    assert "shopping-list normalization preserves v1 schema limits" in shopping_tests
    assert "canonical basket payload excludes completed and retailer-deal rows" in shopping_tests


def test_w3_draft_does_not_switch_production_serving_boundary_yet() -> None:
    dockerfile = read(ROOT / "backend" / "Dockerfile")
    bundler = read(ROOT / "backend" / "app" / "ui_bundle.py")
    html = read(UI / "index.html")
    assert "RUN python -m app.ui_bundle --ui-dir /app/app/ui" in dockerfile
    assert 'app_path = ui_dir / "app.js"' in bundler
    assert 'SCRIPT_TAG = \'<script src="/ui/app.js"></script>\'' in bundler
    assert '<script src="/ui/app.js"></script>' in html
    assert "frontend/dist" not in dockerfile
    assert "/ui/assets/" not in html


def test_w3_build_verifier_fails_closed_on_output_drift() -> None:
    verifier = read(FRONTEND / "scripts" / "verify-build.mjs")
    assert 'relative.length !== 1 || relative[0] !== "app.js"' in verifier
    assert "sourceMappingURL" in verifier
    assert 'name.endsWith(".map")' in verifier
    assert "HERMES_UI_W3_BUILD=PASS" in verifier
    assert "HERMES_UI_W3_BUILD_SHA256" in verifier
    for marker in (
        "Europe/Berlin",
        "hermesDeals.shoppingList.v1",
        "hermesDeals.uiPreferences.v4",
        "hermesDeals.viewPreferences.v5",
        "hermesDeals.filterPanel.v1",
        "hermesDealsReviewRefresh",
        "UiApiError",
        "/api/v1/deals/current",
        "/api/v1/deals/daily-specials",
        "explicit_immutable_retailer_evidence_only",
        "Dati īslaicīgi nav pieejami",
    ):
        assert marker in verifier
