from tests.ui_contract import read_family_ui_contract, ui_response_contract
from pathlib import Path
import unittest


class UiReferenceRebuildV4cTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_family_ui_contract()

    def test_historical_release_identity_metadata_is_retired(self):
        self.assertNotIn('content="reference-v4c-doc-audited"', self.html)
        self.assertIn('id="ui-reference-v4c-layout-fix"', self.html)

    def test_visible_date_keeps_latvian_text_contract(self):
        self.assertIn('id="asOfDisplay"', self.html)
        self.assertIn('type="text"', self.html)
        self.assertIn('placeholder="DD.MM.GGGG"', self.html)
        self.assertIn('maxlength="10"', self.html)

    def test_date_column_has_room_for_full_year(self):
        self.assertIn('grid-template-columns:minmax(300px,1fr) 216px', self.html)
        self.assertIn('#asOfDisplay{', self.html)
        self.assertIn('font-variant-numeric:tabular-nums!important', self.html)

    def test_sidebar_rules_target_real_reference_dom(self):
        self.assertIn('.reference-sidebar .brand-lockup', self.html)
        self.assertIn('.reference-sidebar .side-link.active', self.html)
        self.assertIn('.reference-sidebar .sidebar-bottom', self.html)
        self.assertIn('.reference-sidebar .sidebar-tool', self.html)

    def test_sidebar_active_state_has_modern_indicator(self):
        self.assertIn('.reference-sidebar .side-link::before', self.html)
        self.assertIn('background:#1f8a58!important', self.html)
        self.assertIn('box-shadow:0 10px 24px rgba(40,69,53,.08)!important', self.html)

    def test_catalog_summary_uses_dedicated_non_overlapping_row(self):
        self.assertIn('"toggle title sort"', self.html)
        self.assertIn('"summary summary summary"', self.html)
        self.assertIn('.catalog-summary{', self.html)
        self.assertIn('white-space:normal!important', self.html)

    def test_filter_layout_has_tablet_and_phone_fallbacks(self):
        self.assertIn('@media(max-width:1080px)', self.html)
        self.assertIn('"summary summary"', self.html)
        self.assertIn('@media(max-width:620px)', self.html)

    def test_topbar_hides_secondary_actions_before_overflow(self):
        self.assertIn('@media(max-width:1280px)', self.html)
        self.assertIn('#shareView{display:none!important}', self.html)
        self.assertIn('.topbar .health{display:none!important}', self.html)


if __name__ == "__main__":
    unittest.main()
