import re
import unittest
from pathlib import Path


class UiReferenceRebuildV8Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (
            Path(__file__).resolve().parents[1] / "app" / "ui" / "index.html"
        ).read_text(encoding="utf-8")
        match = re.search(
            r'<style id="ui-reference-v8-calendar-icon-centering">'
            r'(.*?)</style>',
            cls.html,
            re.S,
        )
        if not match:
            raise AssertionError("V8 calendar-icon style block is missing")
        cls.style = match.group(1)

    def test_release_marker_and_style_are_present(self):
        self.assertIn("reference-v8-calendar-icon-centering", self.html)
        self.assertIn('id="ui-reference-v8-calendar-icon-centering"', self.html)

    def test_calendar_button_is_an_explicit_centering_container(self):
        self.assertIn("display:flex!important", self.style)
        self.assertIn("align-items:center!important", self.style)
        self.assertIn("justify-content:center!important", self.style)
        self.assertIn("padding:0!important", self.style)

    def test_generated_icon_has_a_stable_centered_box(self):
        self.assertIn("position:static!important", self.style)
        self.assertIn("flex:0 0 19px!important", self.style)
        self.assertIn("width:19px!important", self.style)
        self.assertIn("height:19px!important", self.style)
        self.assertIn("margin:0!important", self.style)

    def test_visual_glyph_center_is_optically_corrected(self):
        self.assertIn("transform:translateY(1px)!important", self.style)

    def test_native_picker_hit_area_remains_centered_with_button(self):
        self.assertIn(".native-date-proxy", self.style)
        self.assertIn("top:50%!important", self.style)
        self.assertIn("transform:translateY(-50%)!important", self.style)

    def test_existing_date_and_sidebar_contracts_remain_present(self):
        self.assertLess(
            self.html.index('id="ui-reference-v7-stable-sidebar-anchor"'),
            self.html.index('id="ui-reference-v8-calendar-icon-centering"'),
        )
        self.assertIn("text-align:center!important", self.html)
        self.assertIn("reference-v6-single-scroll-sidebar", self.html)


if __name__ == "__main__":
    unittest.main()
