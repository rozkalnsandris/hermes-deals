from tests.ui_contract import read_family_ui_contract, ui_response_contract
import re
import unittest
from pathlib import Path


class UiReferenceRebuildV9bTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_family_ui_contract()
        match = re.search(
            r'<style id="ui-reference-v9-daily-specials-overview">'
            r'(.*?)</style>',
            cls.html,
            re.S,
        )
        if not match:
            raise AssertionError("V9 daily-specials style block is missing")
        cls.style = match.group(1)

    def test_release_marker_and_style_are_present(self):
        self.assertIn("reference-v9-daily-specials-overview", self.html)
        self.assertIn("reference-v9a-legacy-contract", self.html)
        self.assertIn(
            'id="ui-reference-v9-daily-specials-overview"',
            self.html,
        )

    def test_empty_kpi_decorations_are_removed(self):
        self.assertIn(".stat::after", self.style)
        self.assertIn("content:none!important", self.style)
        self.assertIn("display:none!important", self.style)

    def test_kpi_labels_reclaim_full_width(self):
        self.assertIn(".stat-label", self.style)
        self.assertIn("max-width:none!important", self.style)

    def test_today_and_tomorrow_panels_replace_old_best_section(self):
        self.assertNotIn('<section id="bestTodaySection"', self.html)
        self.assertNotIn('<div id="bestToday"', self.html)
        self.assertIn('id="dailySpecialsSection"', self.html)
        self.assertIn('id="todaySpecials"', self.html)
        self.assertIn('id="tomorrowSpecials"', self.html)
        self.assertIn("<h2>Šodien</h2>", self.html)
        self.assertIn("<h2>Rīt</h2>", self.html)

    def test_legacy_best_today_static_contract_is_comment_only(self):
        for marker in (
            'id="bestTodaySection"',
            'id="bestToday"',
            "function bestDealCard(d)",
            "function bestCanonicalCard(p)",
            "function renderBestToday()",
            'data-best-kind="deal"',
            'data-best-kind="canonical"',
            "renderBestToday();bindCanonicalCards()",
        ):
            self.assertIn(marker, self.html)
        self.assertIn(
            "V9b exact archived static contract markers only",
            self.html,
        )
        self.assertNotIn('<section id="bestTodaySection"', self.html)
        self.assertNotIn('<div id="bestToday"', self.html)
        without_comments = re.sub(r"<!--.*?-->", "", self.html, flags=re.S)
        self.assertNotIn("function bestDealCard(d)", without_comments)
        self.assertNotIn("function bestCanonicalCard(p)", without_comments)
        self.assertNotIn("function renderBestToday()", without_comments)
        self.assertNotIn("renderBestToday();bindCanonicalCards()", without_comments)

    def test_one_day_base_offer_predicate_is_exact(self):
        self.assertIn(
            "d.valid_from===iso&&d.valid_until===iso",
            self.html,
        )

    def test_one_day_app_offer_predicate_is_exact(self):
        self.assertIn(
            "d.app_price_eur!=null&&d.app_valid_from===iso"
            "&&d.app_valid_until===iso",
            self.html,
        )

    def test_daily_specials_use_actual_today_not_selected_catalog_date(self):
        self.assertIn(
            "const today=todayLocal(),tomorrow=addDaysIso(today,1)",
            self.html,
        )
        self.assertNotIn(
            "dailySpecialsUrl(asOf.value)",
            self.html,
        )

    def test_both_days_fetch_full_current_offer_sets(self):
        self.assertIn(
            'new URLSearchParams({as_of:iso,view:"current",'
            'sort:"discount_desc",limit:"500",offset:"0"})',
            self.html,
        )
        self.assertIn(
            "Promise.all([fetchJson(dailySpecialsUrl(today)),"
            "fetchJson(dailySpecialsUrl(tomorrow))])",
            self.html,
        )

    def test_retailer_diversity_is_round_robin_and_family_first(self):
        self.assertIn(
            'DAILY_SPECIAL_RETAILER_ORDER=["netto","lidl",'
            '"aldi_nord","edeka"]',
            self.html,
        )
        self.assertIn("while(remaining)", self.html)
        self.assertIn("result.push(group.shift())", self.html)

    def test_special_cards_show_store_price_validity_and_app_badge(self):
        self.assertIn("daily-special-store", self.html)
        self.assertIn("daily-special-price", self.html)
        self.assertIn("daily-special-validity", self.html)
        self.assertIn('daily-special-badge">Lietotnē', self.html)
        self.assertIn('"Tikai šodien"', self.html)
        self.assertIn('"Tikai rīt"', self.html)

    def test_daily_cards_open_existing_raw_detail_dialog(self):
        self.assertIn("specialDealCache.get(card.dataset.specialId)", self.html)
        self.assertIn("openRawDealDetail(deal)", self.html)
        self.assertIn('event.key==="Enter"||event.key===" "', self.html)

    def test_preview_limit_expansion_and_reload_are_wired(self):
        self.assertIn("DAILY_SPECIAL_PREVIEW_LIMIT=6", self.html)
        self.assertIn("data-special-more", self.html)
        self.assertIn(
            "Promise.allSettled([loadOverview(),loadGrid(),loadDailySpecials()])",
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
