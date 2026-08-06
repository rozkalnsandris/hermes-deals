from __future__ import annotations

from tests.ui_contract import read_family_ui_contract, ui_response_contract
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


class UiWeeklyOverviewV3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = read_family_ui_contract()
        cls.active = re.sub(r"<!--.*?-->", "", cls.html, flags=re.S)

    def test_release_markers_and_top_navigation_are_present(self) -> None:
        self.assertIn('content="weekly-overview-v1"', self.html)
        self.assertIn(
            'content="weekly-overview-v2-short-period-filter"',
            self.html,
        )
        self.assertIn(
            'content="weekly-overview-v3-empty-day-polish"',
            self.html,
        )
        for marker in (
            "Nedēļas pārskats",
            "Šodien",
            "Visi piedāvājumi",
            "Pārskatīšana",
        ):
            self.assertIn(marker, self.active)

    def test_semantic_weekly_structure_is_present(self) -> None:
        self.assertIn('<header class="weekly-appbar">', self.active)
        self.assertIn('<nav class="weekly-main-nav"', self.active)
        self.assertIn('<section class="weekly-calendar-shell"', self.active)
        self.assertIn('<aside class="weekly-summary-panel"', self.active)

    def test_week_loader_uses_one_weekly_api_response(self) -> None:
        self.assertIn(
            '/api/v1/deals/weekly-specials',
            self.active,
        )
        self.assertIn(
            'function weeklyBundleUrl(start)',
            self.active,
        )
        self.assertIn(
            'const payload=await fetchJson(weeklyBundleUrl(start))',
            self.active,
        )
        self.assertIn(
            'payload.days||[]',
            self.active,
        )
        self.assertNotIn(
            'async function weeklyFetchDay(iso)',
            self.active,
        )
        self.assertNotIn(
            'weeklyLoadDate',
            self.active,
        )

    def test_weekly_overview_defers_hidden_legacy_requests(self) -> None:
        self.assertIn("loadingDates:new Set()", self.active)
        self.assertIn("pending=weeklyState.loadingDates.has(iso)", self.active)
        self.assertIn("async function openWeeklyDeals", self.active)
        self.assertIn('weeklyNavDeals").addEventListener("click",()=>void openWeeklyDeals())', self.active)
        self.assertNotIn(
            '$("comparisonToggle").style.display=mode==="canonical"?"flex":"none";loadInitialPage();',
            self.active,
        )
        self.assertNotIn("syncUrl();renderWeeklyOverview();reloadAll();", self.active)
        self.assertNotIn("syncUrl();reloadAll();loadWeeklyOverview(target);", self.active)

    def test_full_week_catalog_rows_are_excluded(self) -> None:
        self.assertIn("WEEKLY_SPECIAL_MAX_DAYS=3", self.active)
        self.assertIn(
            "span&&span<=WEEKLY_SPECIAL_MAX_DAYS",
            self.active,
        )
        self.assertIn(
            'if(deal.source_chain!=="netto")',
            self.active,
        )
        self.assertIn(
            "add(deal.valid_from,deal.valid_until,\"base\")",
            self.active,
        )
        self.assertIn(
            "add(deal.app_valid_from,deal.app_valid_until,\"app\")",
            self.active,
        )

    def test_netto_requires_explicit_high_confidence_evidence(self) -> None:
        self.assertIn("deal.is_daily_special===true", self.active)
        self.assertIn("deal.special_valid_on", self.active)
        self.assertIn('deal.special_confidence==="high"', self.active)
        self.assertIn(
            'add(deal.special_valid_on,deal.special_valid_on,"explicit")',
            self.active,
        )

    def test_start_and_continuing_sections_use_qualifying_windows(self) -> None:
        self.assertIn("weeklyWindowForStart(deal,iso)", self.active)
        self.assertIn("weeklyWindowForActive(deal,iso)", self.active)
        self.assertIn("window&&window.start<iso", self.active)
        self.assertIn("weeklyValidity(deal,iso)", self.active)
        self.assertIn("weeklyIsSingleDay(deal,iso)", self.active)

    def test_week_is_monday_to_sunday_and_berlin_aware(self) -> None:
        self.assertIn('timeZone:"Europe/Berlin"', self.active)
        self.assertIn("Array.from({length:7}", self.active)
        self.assertIn("day=date.getDay()||7", self.active)

    def test_existing_catalog_and_raw_detail_flow_remain_available(self) -> None:
        self.assertIn('class="catalog-panel" id="deals"', self.active)
        self.assertIn("openRawDealDetail(deal)", self.active)
        self.assertIn("loadGrid();", self.active)

    def test_responsive_week_and_store_grids_are_defined(self) -> None:
        self.assertIn(
            "grid-template-columns:repeat(7,minmax(150px,1fr))",
            self.active,
        )
        self.assertIn(
            "grid-template-columns:repeat(4,minmax(0,1fr))",
            self.active,
        )
        self.assertIn("@media(max-width:760px)", self.active)

    def test_week_strip_hides_cross_axis_scrollbar(self) -> None:
        self.assertIn("overflow-x:auto", self.active)
        self.assertIn("overflow-y:hidden", self.active)

    def test_empty_selected_day_uses_one_compact_state(self) -> None:
        self.assertIn("function weeklyNextActiveDate(iso)", self.active)
        self.assertIn("function weeklyEmptyDayHtml(iso)", self.active)
        self.assertIn('weeklyStoreGroups.classList.toggle("is-empty",!rows.length)', self.active)
        self.assertIn('weeklyStoreGroups.innerHTML=weeklyEmptyDayHtml(iso)', self.active)
        self.assertIn("data-weekly-empty-next", self.active)
        self.assertIn("weekly-empty-day-action", self.active)

    def test_new_dom_ids_are_unique(self) -> None:
        parser = _IdCollector()
        parser.feed(self.html)
        new_ids = [value for value in parser.ids if value.startswith("weekly")]
        self.assertEqual(len(new_ids), len(set(new_ids)))
        self.assertEqual(parser.ids.count("home"), 1)


if __name__ == "__main__":
    unittest.main()
