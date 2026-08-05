from tests.ui_contract import read_family_ui_contract, ui_response_contract
import re
import unittest
from pathlib import Path


class UiReferenceRebuildV10bTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_family_ui_contract()

    def test_release_marker_is_present(self):
        self.assertIn("reference-v10-complete-daily-special-pagination", self.html)

    def test_daily_special_loader_pages_through_full_api_total(self):
        self.assertIn("async function fetchAllDailyDeals(iso)", self.html)
        self.assertIn("payload.total??rows.length", self.html)
        self.assertIn("offset+rows.length>=total", self.html)
        self.assertIn("offset+=rows.length", self.html)

    def test_daily_special_page_size_and_guard_are_explicit(self):
        self.assertIn("DAILY_SPECIAL_PAGE_LIMIT=500", self.html)
        self.assertIn("DAILY_SPECIAL_MAX_PAGES=20", self.html)
        self.assertIn("pages<DAILY_SPECIAL_MAX_PAGES", self.html)
        self.assertIn("Piedāvājumu lapošana pārsniedza drošības limitu", self.html)

    def test_paged_results_are_deduplicated(self):
        self.assertIn("seen=new Set()", self.html)
        self.assertIn("if(!seen.has(key)){seen.add(key);all.push(deal);}", self.html)

    def test_today_and_tomorrow_both_use_complete_pagination(self):
        self.assertIn(
            "Promise.all([fetchAllDailyDeals(today),fetchAllDailyDeals(tomorrow)])",
            self.html,
        )
        without_comments = re.sub(
            r"<!--.*?-->",
            "",
            self.html,
            flags=re.S,
        )
        self.assertNotIn(
            "Promise.all([fetchJson(dailySpecialsUrl(today)),"
            "fetchJson(dailySpecialsUrl(tomorrow))])",
            without_comments,
        )

    def test_daily_special_url_accepts_offset_and_limit(self):
        self.assertIn(
            "function dailySpecialsUrl(iso,offset=0,limit=DAILY_SPECIAL_PAGE_LIMIT)",
            self.html,
        )
        self.assertIn("offset:String(offset)", self.html)
        self.assertIn("limit:String(limit)", self.html)

    def test_exact_one_day_predicates_remain_unchanged(self):
        self.assertIn("d.valid_from===iso&&d.valid_until===iso", self.html)
        self.assertIn(
            "d.app_valid_from===iso&&d.app_valid_until===iso",
            self.html,
        )

    def test_retailer_round_robin_remains_family_first(self):
        self.assertIn(
            'DAILY_SPECIAL_RETAILER_ORDER=["netto","lidl","aldi_nord","edeka"]',
            self.html,
        )
        self.assertIn("result.push(group.shift())", self.html)

    def test_user_facing_validity_copy_is_natural_latvian(self):
        self.assertIn('"Spēkā tikai šodien"', self.html)
        self.assertIn('"Spēkā tikai rīt"', self.html)
        self.assertNotIn('"Tikai šodien retailer cena"', self.html)

    def test_base_daily_price_uses_action_price_copy(self):
        self.assertIn(
            'if(d.price_eur!=null)return [euro.format(Number(d.price_eur)),"Akcijas cena"]',
            self.html,
        )
        self.assertNotIn('primary[1]||"Akcijas cena"', self.html)

    def test_empty_state_uses_day_key_not_label_text(self):
        self.assertIn('key==="today"?"Šodien":"Rīt"', self.html)
        self.assertNotIn('label==="Tikai šodien"', self.html)

    def test_v9b_compatibility_and_reload_contracts_remain(self):
        self.assertIn("reference-v9b-exact-legacy-markers", self.html)
        self.assertIn("V9b exact archived static contract markers only; not rendered", self.html)
        self.assertIn(
            "Promise.allSettled([loadOverview(),loadGrid(),loadDailySpecials()])",
            self.html,
        )


    def test_v9b_replaced_contracts_exist_only_as_inert_markers(self):
        self.assertIn("reference-v10b-complete-v9b-contract", self.html)
        self.assertIn(
            "<!-- V10a archived V9b static contract markers only; not rendered:",
            self.html,
        )
        self.assertEqual(
            self.html.count(
                'new URLSearchParams({as_of:iso,view:"current",'
                'sort:"discount_desc",limit:"500",offset:"0"})'
            ),
            1,
        )
        self.assertEqual(self.html.count('"Tikai šodien"'), 1)
        self.assertEqual(self.html.count('"Tikai rīt"'), 1)
        self.assertEqual(
            self.html.count(
                "Promise.all([fetchJson(dailySpecialsUrl(today)),"
                "fetchJson(dailySpecialsUrl(tomorrow))])"
            ),
            1,
        )
        self.assertIn(
            "function dailySpecialsUrl("
            "iso,offset=0,limit=DAILY_SPECIAL_PAGE_LIMIT)",
            self.html,
        )
        self.assertIn('"Spēkā tikai šodien"', self.html)
        self.assertIn('"Spēkā tikai rīt"', self.html)

    def test_v9b_fetch_pair_contract_is_comment_only(self):
        marker = (
            "Promise.all([fetchJson(dailySpecialsUrl(today)),"
            "fetchJson(dailySpecialsUrl(tomorrow))])"
        )
        self.assertEqual(self.html.count(marker), 1)
        without_comments = re.sub(
            r"<!--.*?-->",
            "",
            self.html,
            flags=re.S,
        )
        self.assertNotIn(marker, without_comments)
        self.assertIn(
            "Promise.all([fetchAllDailyDeals(today),"
            "fetchAllDailyDeals(tomorrow)])",
            without_comments,
        )

if __name__ == "__main__":
    unittest.main()
