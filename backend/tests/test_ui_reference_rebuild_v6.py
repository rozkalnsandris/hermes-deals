from tests.ui_contract import read_family_ui_contract, ui_response_contract
import re
import unittest
from pathlib import Path


class UiReferenceRebuildV6Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_family_ui_contract()
        match = re.search(
            r'<style id="ui-reference-v6-single-scroll-sidebar">(.*?)</style>',
            cls.html,
            re.S,
        )
        if not match:
            raise AssertionError("V6 sidebar style block is missing")
        cls.style = match.group(1)

    def test_release_marker_and_style_are_present(self):
        self.assertIn("reference-v6-single-scroll-sidebar", self.html)
        self.assertIn(
            'id="ui-reference-v6-single-scroll-sidebar"',
            self.html,
        )

    def test_sidebar_no_longer_owns_a_scroll_area(self):
        self.assertIn("overflow:visible!important", self.style)
        self.assertNotIn("overflow:auto", self.style)
        self.assertNotIn("overflow-y:auto", self.style)

    def test_sidebar_uses_content_height_instead_of_viewport_height(self):
        self.assertIn("height:auto!important", self.style)
        self.assertIn("min-height:0!important", self.style)
        self.assertIn("max-height:none!important", self.style)
        self.assertNotIn("height:100vh", self.style)

    def test_sidebar_stays_page_sticky_without_nested_scrolling(self):
        self.assertIn("position:sticky!important", self.style)
        self.assertIn("top:12px!important", self.style)
        self.assertIn("align-self:start!important", self.style)
        self.assertIn("overscroll-behavior:auto!important", self.style)

    def test_sidebar_bottom_controls_are_compact(self):
        self.assertIn("margin-top:18px!important", self.style)
        self.assertIn("gap:8px!important", self.style)
        self.assertIn("min-height:44px!important", self.style)
        self.assertIn("padding:11px!important", self.style)

    def test_short_desktop_viewports_have_an_extra_compact_contract(self):
        self.assertIn(
            "@media (min-width:921px) and (max-height:820px)",
            self.style,
        )
        self.assertIn("min-height:40px!important", self.style)
        self.assertIn("padding:16px 14px 14px!important", self.style)

    def test_existing_mobile_sidebar_contract_remains_available(self):
        self.assertIn(
            'body[data-ui-release="reference-v1"] '
            ".reference-sidebar{display:none}",
            self.html,
        )
        self.assertIn("@media (max-width:920px)", self.style)
        self.assertIn("position:static!important", self.style)


if __name__ == "__main__":
    unittest.main()
