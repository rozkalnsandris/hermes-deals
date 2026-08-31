from tests.ui_contract import read_family_ui_contract, ui_response_contract
import re
import unittest
from pathlib import Path


class UiReferenceRebuildV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = read_family_ui_contract()

    def test_historical_release_fix_metadata_is_retired(self) -> None:
        self.assertNotIn('content="reference-v2"', self.html)
        self.assertIn('id="ui-reference-v2-fixes"', self.html)

    def test_desktop_legacy_zoom_is_neutralized(self) -> None:
        self.assertIn('body[data-ui-release="reference-v1"]{zoom:1!important}', self.html)

    def test_topbar_no_longer_overlays_scrolled_content(self) -> None:
        self.assertIn('.topbar{position:relative!important;top:auto!important', self.html)

    def test_kpi_legacy_pseudo_icons_are_removed(self) -> None:
        self.assertIn('.stat::before{content:none!important;display:none!important}', self.html)

    def test_best_today_heading_and_cards_have_explicit_layout(self) -> None:
        self.assertIn('.section-title-wrap{display:flex;align-items:center;gap:10px', self.html)
        self.assertIn('.best-card{grid-template-columns:96px minmax(0,1fr)', self.html)

    def test_compact_density_cannot_force_four_broken_columns(self) -> None:
        self.assertIn('.compact-cards .grid{grid-template-columns:repeat(3,minmax(0,1fr))!important', self.html)

    def test_product_cards_have_non_overlapping_three_zone_widths(self) -> None:
        self.assertIn('grid-template-columns:116px minmax(0,1fr) 96px!important', self.html)
        self.assertIn('.product-name{overflow-wrap:anywhere', self.html)

    def test_filter_panel_has_bounded_responsive_structure(self) -> None:
        self.assertIn('.toolbar-main{grid-template-columns:minmax(170px,210px) minmax(0,1fr)', self.html)
        self.assertIn('.catalog-summary{justify-self:end;overflow:hidden;text-overflow:ellipsis}', self.html)

    def test_drawer_and_details_are_restored_to_light_reference_style(self) -> None:
        self.assertIn('.drawer-head,', self.html)
        self.assertIn('background:#fff!important;color:var(--ref-text)!important', self.html)
        self.assertIn('.drawer-footer .btn.primary{background:var(--ref-green)!important', self.html)

    def test_mobile_and_tablet_fallbacks_remain_real_layouts(self) -> None:
        self.assertIn('@media(max-width:920px)', self.html)
        self.assertIn('@media(max-width:620px)', self.html)
        self.assertIn('.best-card{min-width:280px;scroll-snap-align:start}', self.html)


if __name__ == "__main__":
    unittest.main()
