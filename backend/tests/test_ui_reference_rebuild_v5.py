import unittest
from pathlib import Path


class UiReferenceRebuildV5Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("app/ui/index.html").read_text(encoding='utf-8')

    def test_release_marker_and_style_are_present(self):
        self.assertIn('content="reference-v5-details-restoration"', self.html)
        self.assertIn('id="ui-reference-v5-details-restoration"', self.html)

    def test_date_text_and_picker_are_centered(self):
        self.assertIn('justify-content:center!important;', self.html)
        self.assertIn('#asOfDisplay{', self.html)
        self.assertIn('text-align:center!important;', self.html)

    def test_card_list_action_is_explicit_not_an_ambiguous_plus(self):
        self.assertIn('Sarakstam +', self.html)
        self.assertIn('content:none!important;', self.html)
        self.assertIn('min-width:88px!important;', self.html)

    def test_list_action_has_accessible_labels(self):
        self.assertIn('Pievienot piedāvājumu iepirkumu sarakstam', self.html)
        self.assertIn('Pievienot produktu iepirkumu sarakstam', self.html)
        self.assertIn('aria-label="${esc(listTitle)}"', self.html)

    def test_plus_action_stops_overlay_propagation(self):
        self.assertIn('event.stopPropagation();addDealToList(deal)', self.html)
        self.assertIn('event.stopPropagation();addToList(p)', self.html)

    def test_raw_details_always_explain_price_history(self):
        self.assertIn('async function openRawDealDetail', self.html)
        self.assertIn('detailHistoryHtml(historyRows,historyCopy)', self.html)
        self.assertIn('Cenu vēsture būs pieejama pēc tam', self.html)
        self.assertIn('Tikai retailer deal', self.html)
        self.assertIn('Canonical salīdzināms', self.html)

    def test_canonical_details_restore_history_and_comparison(self):
        self.assertIn('detailComparisonHtml(offers)', self.html)
        self.assertIn('detailHistoryHtml(rows)', self.html)
        self.assertIn('/price-history?limit=60', self.html)

    def test_details_are_centered_in_a_bounded_shell(self):
        self.assertIn('.detail-shell{', self.html)
        self.assertIn('max-width:920px!important;', self.html)
        self.assertIn('transform:translateX(-50%)!important;', self.html)

    def test_missing_image_uses_named_placeholder_not_letter_h(self):
        self.assertIn('Attēls nav pieejams', self.html)
        self.assertIn('function detailImageHtml', self.html)

    def test_detail_layout_has_mobile_fallbacks(self):
        self.assertIn('@media(max-width:900px)', self.html)
        self.assertIn('@media(max-width:620px)', self.html)
        self.assertIn('grid-template-columns:1fr!important;', self.html)


if __name__ == '__main__':
    unittest.main()

