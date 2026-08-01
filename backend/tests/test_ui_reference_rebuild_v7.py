import re
import unittest
from pathlib import Path

class UiReferenceRebuildV7Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parents[1] / "app" / "ui" / "index.html").read_text(encoding="utf-8")
        match = re.search(r'<style id="ui-reference-v7-stable-sidebar-anchor">(.*?)</style>', cls.html, re.S)
        if not match:
            raise AssertionError("V7 stable-sidebar style block is missing")
        cls.style = match.group(1)

    def test_release_marker_and_style_are_present(self):
        self.assertIn("reference-v7-stable-sidebar-anchor", self.html)
        self.assertIn('id="ui-reference-v7-stable-sidebar-anchor"', self.html)

    def test_audited_html_keeps_sidebar_as_direct_grid_child(self):
        shell = self.html.index('<div class="ui2-shell reference-app">')
        sidebar = self.html.index('<aside class="reference-sidebar" aria-label="Galvenā navigācija">')
        workspace = self.html.index('<div class="reference-workspace">', sidebar)
        self.assertLess(shell, sidebar)
        self.assertLess(sidebar, workspace)

    def test_grid_padding_and_sticky_threshold_share_one_anchor(self):
        self.assertIn("--reference-sidebar-anchor:20px", self.style)
        self.assertIn("padding-top:var(--reference-sidebar-anchor)!important", self.style)
        self.assertIn("top:var(--reference-sidebar-anchor)!important", self.style)

    def test_desktop_anchor_override_is_after_v6_contract(self):
        self.assertLess(self.html.index('id="ui-reference-v6-single-scroll-sidebar"'), self.html.index('id="ui-reference-v7-stable-sidebar-anchor"'))
        self.assertIn("@media (min-width:921px)", self.style)

    def test_sticky_and_single_scroll_contract_remain_intact(self):
        self.assertIn("position:sticky!important", self.style)
        self.assertIn("align-self:start!important", self.style)
        self.assertNotIn("overflow:auto", self.style)
        self.assertNotIn("overflow-y:auto", self.style)

    def test_browser_scrollbar_space_is_stable(self):
        self.assertIn("scrollbar-gutter:stable", self.style)

    def test_mobile_contract_is_not_overridden(self):
        self.assertNotIn("@media (max-width:920px)", self.style)
        self.assertIn('body[data-ui-release="reference-v1"] .reference-sidebar{display:none}', self.html)

if __name__ == "__main__":
    unittest.main()
