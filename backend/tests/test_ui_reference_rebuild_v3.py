from tests.ui_contract import read_family_ui_contract, ui_response_contract
from pathlib import Path
import unittest


class UiReferenceRebuildV3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = read_family_ui_contract()

    def test_release_fix_identity_is_explicit(self):
        self.assertIn('content="reference-v3-hover"', self.html)
        self.assertIn('id="ui-reference-v3-hover-fix"', self.html)

    def test_full_card_detail_hover_stays_transparent(self):
        self.assertIn('.actions .detail-btn:hover', self.html)
        self.assertIn('.actions .raw-detail:hover', self.html)
        self.assertIn('background:transparent!important', self.html)

    def test_full_card_detail_active_and_focus_do_not_paint_overlay(self):
        self.assertIn('.actions .detail-btn:active', self.html)
        self.assertIn('.actions .raw-detail:focus', self.html)
        self.assertIn('box-shadow:none!important', self.html)

    def test_keyboard_focus_remains_visible_without_gray_fill(self):
        self.assertIn('.actions .detail-btn:focus-visible', self.html)
        self.assertIn('outline:3px solid rgba(31,122,80,.34)', self.html)
        self.assertIn('outline-offset:-4px', self.html)


if __name__ == "__main__":
    unittest.main()
