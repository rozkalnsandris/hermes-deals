from tests.ui_contract import read_family_ui_contract, ui_response_contract
import re
import unittest
from pathlib import Path


class UiReferenceRebuildV1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = read_family_ui_contract()

    def test_release_identity_and_reference_scope_are_explicit(self) -> None:
        self.assertIn('content="reference-v1"', self.html)
        self.assertIn('data-ui-release="reference-v1"', self.html)
        self.assertIn('id="ui-reference-v1"', self.html)

    def test_desktop_dom_is_real_sidebar_workspace_layout(self) -> None:
        self.assertIn('class="ui2-shell reference-app"', self.html)
        self.assertIn('class="reference-sidebar"', self.html)
        self.assertIn('class="reference-workspace"', self.html)
        self.assertIn('grid-template-columns:230px minmax(0,1fr)', self.html)

    def test_topbar_matches_search_date_actions_health_and_avatar(self) -> None:
        for marker in ('id="search"', 'id="asOfDisplay"', 'id="refreshView"', 'id="shareView"', 'id="health"', 'class="avatar-button"'):
            self.assertIn(marker, self.html)
        self.assertIn('grid-template-columns:minmax(320px,1fr) 176px auto auto auto 46px', self.html)

    def test_hero_moves_quick_dates_beside_real_heading(self) -> None:
        self.assertIn('<h1>Cenas bez minējumiem.</h1>', self.html)
        self.assertIn('class="hero-actions"', self.html)
        self.assertIn('id="quickDates"', self.html)
        self.assertIn('Drošais salīdzināšanas skats rāda tikai apstiprinātas produktu identitātes.', self.html)

    def test_kpis_are_four_distinct_colored_cards(self) -> None:
        for marker in ('stat-green', 'stat-blue', 'stat-purple', 'stat-orange', 'class="stat-icon"'):
            self.assertIn(marker, self.html)
        self.assertIn('grid-template-columns:repeat(4,minmax(0,1fr))', self.html)

    def test_archived_best_today_contract_is_not_shipped(self) -> None:
        for marker in (
            'id="bestTodaySection"',
            'id="bestToday"',
            'function bestDealCard',
            'function bestCanonicalCard',
            'data-best-kind="canonical"',
            'renderBestToday();bindCanonicalCards()',
        ):
            self.assertNotIn(marker, self.html)

    def test_filter_area_is_a_real_catalog_panel_not_old_toolbar(self) -> None:
        self.assertIn('class="catalog-panel" id="deals"', self.html)
        self.assertIn('id="retailerSelect"', self.html)
        self.assertIn('class="catalog-sort"', self.html)
        self.assertIn('stored===null||stored==="open"', self.html)

    def test_retailer_select_is_wired_to_existing_filter_state(self) -> None:
        self.assertIn('$("retailerSelect")?.addEventListener("change"', self.html)
        self.assertIn('$("retailerSelect").value=selectedRetailer', self.html)
        self.assertIn('$("retailerSelect").value=""', self.html)

    def test_product_cards_use_new_three_zone_dom(self) -> None:
        self.assertIn('class="card reference-product-card"', self.html)
        self.assertIn('class="product-footer"', self.html)
        self.assertIn('class="product-chevron"', self.html)
        self.assertIn('grid-template-columns:128px minmax(0,1fr) 112px', self.html)

    def test_card_actions_remain_functional_but_visually_minimal(self) -> None:
        for marker in ('class="btn raw-detail"', 'deal-list-add', 'class="btn detail-btn"', 'list-add'):
            self.assertIn(marker, self.html)
        self.assertIn('.detail-btn,body[data-ui-release="reference-v1"] .raw-detail{inset:0', self.html)

    def test_mobile_has_real_header_stack_and_five_item_navigation(self) -> None:
        self.assertIn('class="mobile-brand-row"', self.html)
        self.assertIn('grid-template-columns:repeat(5,1fr)', self.html)
        self.assertIn('<span>Pārskatīšana</span>', self.html)
        self.assertIn('@media(max-width:920px)', self.html)

    def test_required_ids_are_unique_in_static_dom(self) -> None:
        ids = re.findall(r'id="([^"]+)"', self.html)
        literal_ids = [value for value in ids if '${' not in value]
        duplicates = sorted({value for value in literal_ids if literal_ids.count(value) > 1})
        self.assertEqual(duplicates, [])


if __name__ == "__main__":
    unittest.main()
