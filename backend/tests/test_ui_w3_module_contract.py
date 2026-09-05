from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "backend" / "frontend"
UI = ROOT / "backend" / "app" / "ui"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_w3_build_contract_is_pinned_and_framework_free() -> None:
    package = json.loads(read(FRONTEND / "package.json"))
    assert package["private"] is True
    assert package["type"] == "module"
    assert package["engines"] == {"node": ">=22.12.0"}
    assert package["devDependencies"] == {"vite": "8.1.5"}
    expected_w3_scripts = {
        "test": "node --test tests/*.test.mjs",
        "build": "node node_modules/vite/bin/vite.js build --config vite.config.js",
        "build:check": "node node_modules/vite/bin/vite.js build --config vite.config.js && node scripts/verify-build.mjs",
    }
    for name, command in expected_w3_scripts.items():
        assert package["scripts"].get(name) == command
    assert read(FRONTEND / ".nvmrc") == "24.18.0\n"
    forbidden = {"react", "react-dom", "vue", "svelte", "@angular/core"}
    declared = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
    assert forbidden.isdisjoint(declared)


def test_w3_vite_output_is_one_classic_non_sourcemapped_iife() -> None:
    config = read(FRONTEND / "vite.config.js")
    assert 'entry: resolve(root, "src/app.js")' in config
    assert 'name: "HermesDealsUI"' in config
    assert 'formats: ["iife"]' in config
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


def test_w3_entry_is_side_effect_only_and_bootstrap_owns_module_graph() -> None:
    entry = read(FRONTEND / "src" / "app.js")
    bootstrap = read(FRONTEND / "src" / "bootstrap.js")

    assert 'from "./core/weekly-payload-bridge.js"' in entry
    assert 'from "./bootstrap.js"' in entry
    assert "installWeeklyPayloadBridge(window)" in entry
    assert "bootstrapUi();" in entry
    assert not any(line.lstrip().startswith("export ") for line in entry.splitlines())

    for path in (
        "./core/api.js",
        "./core/dom.js",
        "./core/dates.js",
        "./core/storage.js",
        "./features/deals.js",
        "./features/daily-specials.js",
        "./features/catalog.js",
        "./features/details.js",
        "./features/shopping-list.js",
        "./features/weekly.js",
        "./ui/filters.js",
        "./ui/navigation.js",
        "./ui/overlays.js",
        "./ui/review-refresh.js",
        "./ui/status.js",
    ):
        assert f'from "{path}"' in bootstrap


def test_w3_core_modules_pin_existing_browser_contracts() -> None:
    api = read(FRONTEND / "src" / "core" / "api.js")
    dates = read(FRONTEND / "src" / "core" / "dates.js")
    dom = read(FRONTEND / "src" / "core" / "dom.js")
    storage = read(FRONTEND / "src" / "core" / "storage.js")
    legacy = read(UI / "app.js")

    for key in (
        "hermesDeals.shoppingList.v1",
        "hermesDeals.uiPreferences.v4",
        "hermesDeals.viewPreferences.v5",
        "hermesDeals.filterPanel.v1",
        "hermesDealsReviewRefresh",
    ):
        assert key in storage
        assert key in legacy
    assert 'timeZone: BERLIN_TIME_ZONE' in dates
    assert 'const BERLIN_TIME_ZONE = "Europe/Berlin"' in dates
    assert "export class UiApiError" in api
    assert "export async function fetchJson" in api
    assert 'response.headers.get("cf-ray")' in api
    assert "export function esc" in dom
    assert '["http:", "https:"]' in dom


def test_w3_current_deals_module_preserves_request_render_and_race_contracts() -> None:
    deals = read(FRONTEND / "src" / "features" / "deals.js")
    legacy = read(UI / "app.js")

    assert "export const PAGE_SIZE = 12" in deals
    assert "export function initCurrentDeals" in deals
    assert "/api/v1/deals/current" in deals
    assert 'view: dealView === "upcoming" ? "upcoming" : "current"' in deals
    assert "let requestGeneration = 0" in deals
    assert "const request = ++requestGeneration" in deals
    assert "request === requestGeneration && isCurrent()" in deals
    for marker in ("app_only", "coupon_only", "discount_only", "image_only"):
        assert marker in deals
        assert marker in legacy
    for marker in ("unit_price_only", "example_total_plus_unit", "app_example_total_plus_unit"):
        assert marker in deals
        assert marker in legacy
    for text in (
        "Dati īslaicīgi nav pieejami",
        "Šim filtram nav drīzumā gaidāmu piedāvājumu.",
        "Šim filtram nav aktuālu piedāvājumu.",
    ):
        assert text in deals
        assert text in legacy


def test_w3_daily_special_module_preserves_explicit_evidence_contract() -> None:
    daily = read(FRONTEND / "src" / "features" / "daily-specials.js")
    legacy = read(UI / "app.js")

    assert "export function initDailySpecials" in daily
    assert 'DAILY_SPECIAL_SOURCE_CONTRACT = "explicit_immutable_retailer_evidence_only"' in daily
    assert "/api/v1/deals/daily-specials" in daily
    assert "payload.source_contract !== DAILY_SPECIAL_SOURCE_CONTRACT" in daily
    assert 'deal.special_confidence === "high"' in daily
    assert 'deal.special_valid_on === iso' in daily
    assert "legacyCurrentDealDailySpecialContract" not in daily
    assert "fetchAllDailyDeals" not in daily
    assert "legacyDailySpecialsUrl" not in daily
    assert "DAILY_SPECIAL_PAGE_LIMIT" not in daily
    assert "DAILY_SPECIAL_MAX_PAGES" not in daily
    assert "/api/v1/deals/current" not in daily
    for marker in (
        "explicit_immutable_retailer_evidence_only",
        "Šodienas īpašās akcijas neizdevās ielādēt.",
        "Rītdienas īpašās akcijas neizdevās ielādēt.",
    ):
        assert marker in daily
        assert marker in legacy


def test_w3_shopping_list_module_preserves_storage_and_basket_contracts() -> None:
    shopping = read(FRONTEND / "src" / "features" / "shopping-list.js")
    legacy = read(UI / "app.js")

    assert "export function initShoppingList" in shopping
    assert "STORAGE_KEY" in shopping
    assert "Math.max(1, Math.min(99" in shopping
    assert ".slice(0, 160)" in shopping
    assert "/api/v1/ui/basket/compare" in shopping
    assert "canonical_product_id" in shopping
    for marker in (
        "hermesDeals.shoppingList.v1",
        "/api/v1/ui/basket/compare",
        "canonical_product_id",
        "Konkrēts veikala piedāvājums",
        "Canonical produkts",
    ):
        assert marker in legacy


def test_w3_release_path_consumes_build_but_keeps_inline_w3_contract() -> None:
    dockerfile = read(ROOT / "backend" / "Dockerfile")
    bundler = read(ROOT / "backend" / "app" / "ui_bundle.py")
    html = read(UI / "index.html")

    assert "AS ui-build" in dockerfile
    assert "COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js" in dockerfile
    assert "RUN python -m app.ui_bundle --ui-dir /app/app/ui" in dockerfile
    assert 'app_path = ui_dir / "app.js"' in bundler
    assert 'WEEKLY_BRIDGE_TAG = \'<script src="/ui/weekly-payload-bridge.js"></script>\'' in bundler
    assert 'SCRIPT_TAG = \'<script src="/ui/app.js"></script>\'' in bundler
    assert "w3-behavior-preserving-bootstrap-v1" in bundler
    assert "normalized_unique_deals_by_id_v1" in bundler
    assert '<script src="/ui/weekly-payload-bridge.js"></script>' in html
    assert '<script src="/ui/app.js"></script>' in html
    assert "/ui/assets/" not in html


def test_w3_build_verifier_fails_closed_on_output_drift_and_module_syntax() -> None:
    verifier = read(FRONTEND / "scripts" / "verify-build.mjs")

    assert 'relative.length !== 1 || relative[0] !== "app.js"' in verifier
    assert "sourceMappingURL" in verifier
    assert 'name.endsWith(".map")' in verifier
    assert "retained ES module syntax" in verifier
    assert "HERMES_UI_W3_BUILD=PASS" in verifier
    assert "HERMES_UI_W3_CLASSIC_SCRIPT=PASS" in verifier
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
        "w3-behavior-preserving-bootstrap-v1",
    ):
        assert marker in verifier
