from __future__ import annotations

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


class UiWeeklyOverviewV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "index.html"
        ).read_text(encoding="utf-8")
        cls.active = re.sub(r"<!--.*?-->", "", cls.html, flags=re.S)

    def test_release_marker_and_top_navigation_are_present(self) -> None:
        self.assertIn('content="weekly-overview-v1"', self.html)
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

    def test_week_loader_reuses_existing_paginated_get_contract(self) -> None:
        self.assertIn(
            "async function weeklyFetchDay(iso){return fetchAllDailyDeals(iso);}",
            self.active,
        )
        self.assertIn(
            "Promise.allSettled(dates.map(weeklyFetchDay))",
            self.active,
        )
        self.assertIn(
            "payload.available_count??payload.total??rows.length",
            self.active,
        )

    def test_start_day_is_derived_from_explicit_validity_fields(self) -> None:
        self.assertIn("deal.valid_from,deal.app_valid_from", self.active)
        self.assertIn("weeklyStartDate(deal)===iso", self.active)
        self.assertIn("deal.valid_from===deal.valid_until", self.active)

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

    def test_new_dom_ids_are_unique(self) -> None:
        parser = _IdCollector()
        parser.feed(self.html)
        new_ids = [value for value in parser.ids if value.startswith("weekly")]
        self.assertEqual(len(new_ids), len(set(new_ids)))
        self.assertEqual(parser.ids.count("home"), 1)


if __name__ == "__main__":
    unittest.main()
