from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "backend" / "frontend"
LEGACY = ROOT / "backend" / "app" / "ui" / "app.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_w3_entry_is_a_side_effect_browser_bootstrap_for_classic_bundle() -> None:
    entry = read(FRONTEND / "src" / "app.js")
    bootstrap = read(FRONTEND / "src" / "bootstrap.js")

    assert 'from "./core/weekly-payload-bridge.js"' in entry
    assert 'from "./bootstrap.js"' in entry
    assert 'typeof window !== "undefined" && typeof document !== "undefined"' in entry
    assert "installWeeklyPayloadBridge(window)" in entry
    assert "bootstrapUi();" in entry
    assert "export " not in entry
    assert 'BOOTSTRAP_CONTRACT = "w3-behavior-preserving-bootstrap-v1"' in bootstrap


def test_w3_bootstrap_preserves_legacy_state_timing_and_mode_contracts() -> None:
    bootstrap = read(FRONTEND / "src" / "bootstrap.js")
    legacy = read(LEGACY)

    for marker in (
        "SEARCH_DEBOUNCE_MS = 250",
        "TOAST_DURATION_MS = 2200",
        "Ievadi datumu formātā DD.MM.GGGG",
        "Raw deal nav automātiski tas pats produkts citā veikalā.",
        "Šajā skatā ir tikai apstiprinātie canonical produkti.",
        'event.key === "/"',
        'event.key !== "Escape"',
        "window.scrollY > 600",
    ):
        assert marker in bootstrap

    assert "setTimeout(()=>{syncUrl();loadGrid();},250)" in legacy
    assert 'toastTimer=setTimeout(()=>toast.classList.remove("show"),2200)' in legacy
    assert "Ievadi datumu formātā DD.MM.GGGG" in legacy
    assert "Raw deal nav automātiski tas pats produkts citā veikalā." in legacy
    assert "Šajā skatā ir tikai apstiprinātie canonical produkti." in legacy


def test_w3_bootstrap_preserves_startup_boundary_without_silent_extra_requests() -> None:
    bootstrap = read(FRONTEND / "src" / "bootstrap.js")
    legacy = read(LEGACY)

    assert "async function loadInitialPage()" in bootstrap
    assert "async function loadInitialPage()" in legacy
    assert "Promise.allSettled([" in bootstrap
    assert "loadOverview()," in bootstrap
    assert "loadGrid()," in bootstrap
    assert "dailyController.load()," in bootstrap

    after_definition = bootstrap.split("async function loadInitialPage()", 1)[1]
    assert "await loadInitialPage()" not in after_definition
    assert "void loadInitialPage()" not in after_definition
    assert "initWeeklyOverview({" in bootstrap


def test_w3_status_module_preserves_health_overview_review_and_error_contracts() -> None:
    status = read(FRONTEND / "src" / "ui" / "status.js")
    legacy = read(LEGACY)

    for marker in (
        "/api/health",
        "/api/v1/ui/overview?as_of=",
        "/api/v1/review-items?source_chain=lidl&limit=500",
        "API pārbaude…",
        "API kļūda",
        "Datus neizdevās ielādēt.",
        "Mēģināt vēlreiz",
        "Jaunākie aktīvie bukleti:",
    ):
        assert marker in status
        assert marker in legacy


def test_w3_preferences_filters_and_deal_details_are_explicit_boundaries() -> None:
    storage = read(FRONTEND / "src" / "core" / "storage.js")
    filters = read(FRONTEND / "src" / "ui" / "filters.js")
    details = read(FRONTEND / "src" / "features" / "details.js")
    bootstrap = read(FRONTEND / "src" / "bootstrap.js")

    assert "normalizeUiPrefs" in storage
    assert "normalizeViewPrefs" in storage
    assert "loadFilterPanelOpen" in storage
    assert "saveFilterPanelOpen" in storage
    assert "export function normalizeSortForMode" in filters
    assert "export function activeFilterLabels" in filters
    assert "export function initDealDetails" in details
    assert "Canonical identitāte apstiprināta" in details
    assert "Tikai retailer deal" in details
    assert 'from "./features/details.js"' in bootstrap
    assert 'from "./ui/filters.js"' in bootstrap
    assert 'from "./ui/status.js"' in bootstrap


def test_w3_bootstrap_node_tests_exist() -> None:
    tests = read(FRONTEND / "tests" / "bootstrap-filter.test.mjs")
    details_tests = read(FRONTEND / "tests" / "storage-details.test.mjs")

    assert "bootstrap identity and legacy timing constants remain explicit" in tests
    assert "bootstrap source preserves legacy startup boundary" in tests
    assert "mode-specific sort normalization preserves legacy rules" in tests
    assert "view preferences fail closed to supported modes retailers sorts" in details_tests
    assert "retailer detail canonical requests remain exactly two" in details_tests
