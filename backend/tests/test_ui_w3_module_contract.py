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


def test_w3_current_deals_primitives_preserve_request_and_render_contracts() -> None:
    app = read(FRONTEND / "src" / "app.js")
    deals = read(FRONTEND / "src" / "features" / "deals.js")
    legacy = read(UI / "app.js")

    assert 'from "./features/deals.js"' in app
    assert "export const PAGE_SIZE = 12" in deals
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


def test_w3_daily_special_module_preserves_explicit_evidence_contract() -> None:
    app = read(FRONTEND / "src" / "app.js")
    daily = read(FRONTEND / "src" / "features" / "daily-specials.js")
    legacy = read(UI / "app.js")

    assert 'from "./features/daily-specials.js"' in app
    assert "export function initDailySpecials" in daily
    assert "/api/v1/deals/daily-specials" in daily
    assert 'payload.source_contract !== "explicit_immutable_retailer_evidence_only"' in daily
    assert 'deal.special_confidence === "high"' in daily
    assert 'deal.special_valid_on === iso' in daily
    assert "legacyCurrentDealDailySpecialContract" in daily
    assert "/api/v1/deals/current" in daily
    assert "MAX_PAGES = 20" in daily

    for marker in (
        "explicit_immutable_retailer_evidence_only",
        "legacyCurrentDealDailySpecialContract",
        "DAILY_SPECIAL_MAX_PAGES=20",
    ):
        assert marker in legacy


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
    ):
        assert marker in verifier
