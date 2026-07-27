from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.parsers.netto import NettoParserContext, parse_netto_html


class NettoParserTest(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "netto_offers.html"
        self.html = fixture.read_bytes()
        self.context = NettoParserContext(
            snapshot_id=uuid4(),
            source_url="https://www.netto-online.de/filialen/example",
            collected_at=datetime.now(timezone.utc),
            store_external_id="6071",
            store_name="Netto Test",
        )

    def test_parses_expected_cards(self):
        offers = parse_netto_html(self.html, self.context)
        self.assertEqual(len(offers), 5)

    def test_action_price(self):
        offer = parse_netto_html(self.html, self.context)[0]
        self.assertEqual(offer.price_eur, Decimal("2.79"))
        self.assertIsNone(offer.regular_price_eur)
        self.assertEqual(offer.package_text_raw, "230 g")

    def test_statt_and_unit_price(self):
        offer = parse_netto_html(self.html, self.context)[1]
        self.assertEqual(offer.product_name_raw, "Trauben dunkel 500 g Schale")
        self.assertEqual(offer.regular_price_eur, Decimal("1.99"))
        self.assertEqual(offer.price_eur, Decimal("1.69"))
        self.assertEqual(offer.unit_price_eur, Decimal("3.38"))
        self.assertEqual(offer.unit_label, "kg")
        self.assertEqual(offer.discount_percent, 15)

    def test_uvp_price(self):
        offer = parse_netto_html(self.html, self.context)[2]
        self.assertEqual(offer.regular_price_eur, Decimal("4.99"))
        self.assertEqual(offer.price_eur, Decimal("3.49"))

    def test_whole_euro_dash_price(self):
        offers = parse_netto_html(self.html, self.context)
        self.assertEqual(offers[3].price_eur, Decimal("1.00"))
        self.assertEqual(offers[4].price_eur, Decimal("1.00"))

    def test_source_identity_is_preserved(self):
        offer = parse_netto_html(self.html, self.context)[0]
        self.assertEqual(offer.source_store_external_id, "6071")
        self.assertEqual(offer.parser_version, "netto-v1")
        self.assertTrue(offer.source_offer_id)


if __name__ == "__main__":
    unittest.main()
