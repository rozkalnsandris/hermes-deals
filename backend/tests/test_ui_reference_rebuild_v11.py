from tests.ui_contract import read_family_ui_contract, ui_response_contract
import re
import unittest
from pathlib import Path


class UiReferenceRebuildV11Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_family_ui_contract()
        cls.active = re.sub(r"<!--.*?-->", "", cls.html, flags=re.S)

    def test_historical_release_marker_is_retired(self):
        self.assertIn('content="reference-v1"', self.html)
        self.assertNotIn("reference-v11-explicit-daily-special-api", self.html)

    def test_ui_uses_explicit_daily_special_endpoint(self):
        self.assertIn("/api/v1/deals/daily-specials?", self.active)
        self.assertIn("function fetchExplicitDailySpecials(iso)", self.active)

    def test_loader_requires_source_backed_contract(self):
        self.assertIn('payload.source_contract!=="explicit_immutable_retailer_evidence_only"', self.active)

    def test_loader_requires_explicit_high_confidence_fields(self):
        self.assertIn("deal.is_daily_special===true", self.active)
        self.assertIn("deal.special_valid_on===iso", self.active)
        self.assertIn('deal.special_confidence==="high"', self.active)

    def test_today_and_tomorrow_use_explicit_endpoint(self):
        self.assertIn("Promise.all([fetchExplicitDailySpecials(today),fetchExplicitDailySpecials(tomorrow)])", self.active)

    def test_active_loader_no_longer_filters_by_plain_one_day_validity(self):
        start = self.active.index("async function loadDailySpecials()")
        end = self.active.index("function updateControlRoomStatus", start)
        loader = self.active[start:end]
        self.assertNotIn("isOneDaySpecialForDate", loader)
        self.assertNotIn("fetchAllDailyDeals(today)", loader)

    def test_v10c_pagination_contract_remains_nonregressed(self):
        self.assertIn("async function fetchAllDailyDeals(iso)", self.active)
        self.assertIn("payload.available_count??payload.total??rows.length", self.active)
        self.assertIn("Promise.all([fetchAllDailyDeals(today),fetchAllDailyDeals(tomorrow)])", self.active)

    def test_existing_cards_keep_raw_detail_flow(self):
        self.assertIn("specialDealCache.get(card.dataset.specialId)", self.active)
        self.assertIn("openRawDealDetail(deal)", self.active)


if __name__ == "__main__":
    unittest.main()
