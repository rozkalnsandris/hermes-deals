from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.parsers.aldi_nord import (
    AldiNordParserContext,
    parse_aldi_nord_html,
)
from app.schemas import SourceChain


def _html_with_offer_map(offer_map: dict[str, object]) -> bytes:
    api_data = [
        [
            "OFFER_GET",
            {
                "req": {"locale": "de", "week": "next"},
                "res": {
                    "algoliaDataMap": offer_map,
                    "categories": [],
                    "weekSwitchPer": {},
                },
            },
        ],
        ["PAGE_MGNL_GET", {"req": {}, "res": {}}],
    ]
    next_data = {
        "buildId": "test-build",
        "page": "/offers-next",
        "props": {
            "pageProps": {
                "apiData": json.dumps(api_data, ensure_ascii=False),
            }
        },
    }
    return (
        '<!doctype html><html><body>'
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data, ensure_ascii=False)
        + "</script></body></html>"
    ).encode("utf-8")


class AldiNordParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = AldiNordParserContext(
            snapshot_id=uuid4(),
            source_url="https://www.aldi-nord.de/angebote-vorschau.html",
            collected_at=datetime(2026, 7, 24, 17, 0, tzinfo=timezone.utc),
        )
        self.offer_map = {
            "2052": {
                "objectID": "2052",
                "name": "Süßes Gericht",
                "brandName": "MONDAMIN",
                "shortDescription": "Verschiedene Sorten",
                "salesUnit": "Packung",
                "assets": [
                    {
                        "type": "product",
                        "url": "https://example.test/images/2052.jpg",
                    }
                ],
                "currentPrice": {
                    "priceValue": 0.89,
                    "strikePrice": {"strikePriceValue": 1.49},
                    "basePrice": [
                        {"basePriceValue": 10, "basePriceScale": "kg"}
                    ],
                    "validFrom": 1785103200,
                    "validUntil": 1785621599,
                },
                "promotionPrices": [
                    {
                        "priceValue": 0.89,
                        "validFromLocalDate": "2026-07-27",
                        "validUntilLocalDate": "2026-08-01",
                    }
                ],
            },
            "3758": {
                "objectID": "3758",
                "name": "Slips",
                "brandName": "UP2FASHION",
                "salesUnit": "7er-Packung",
                "assets": [
                    {
                        "type": "product",
                        "url": "https://example.test/images/3758.jpg",
                    }
                ],
                "currentPrice": {
                    "priceValue": 6.99,
                    "validFrom": 1785362400,
                    "validUntil": 1785621599,
                },
                "promotionPrices": [
                    {
                        "priceValue": 6.99,
                        "validFromLocalDate": "2026-07-30",
                        "validUntilLocalDate": "2026-08-01",
                    }
                ],
            },
            "1042929": {
                "objectID": "1042929",
                "name": "Kreatinpulver",
                "salesUnit": "Dose",
                "assets": [],
            },
        }

    def test_parses_structured_rows_and_skips_missing_current_price(self) -> None:
        offers = parse_aldi_nord_html(
            _html_with_offer_map(self.offer_map),
            self.context,
        )
        self.assertEqual(len(offers), 2)
        self.assertEqual(
            [offer.source_offer_id for offer in offers],
            ["2052", "3758"],
        )

    def test_maps_price_regular_unit_validity_and_image(self) -> None:
        offer = parse_aldi_nord_html(
            _html_with_offer_map(self.offer_map),
            self.context,
        )[0]

        self.assertEqual(offer.source_chain, SourceChain.ALDI_NORD)
        self.assertEqual(offer.product_name_raw, "Süßes Gericht")
        self.assertEqual(offer.brand_raw, "MONDAMIN")
        self.assertEqual(offer.description_raw, "Verschiedene Sorten")
        self.assertEqual(offer.package_text_raw, "Packung")
        self.assertEqual(offer.price_eur, Decimal("0.89"))
        self.assertEqual(offer.regular_price_eur, Decimal("1.49"))
        self.assertEqual(offer.unit_price_eur, Decimal("10"))
        self.assertEqual(offer.unit_label, "kg")
        self.assertEqual(offer.valid_from, date(2026, 7, 27))
        self.assertEqual(offer.valid_until, date(2026, 8, 1))
        self.assertEqual(
            str(offer.source_image_url),
            "https://example.test/images/2052.jpg",
        )
        self.assertEqual(offer.parser_version, "aldi-nord-v1")

    def test_uses_epoch_validity_as_fallback(self) -> None:
        row = dict(self.offer_map["3758"])
        row["promotionPrices"] = []
        offers = parse_aldi_nord_html(
            _html_with_offer_map({"3758": row}),
            self.context,
        )
        self.assertEqual(len(offers), 1)
        self.assertIsNotNone(offers[0].valid_from)
        self.assertIsNotNone(offers[0].valid_until)

    def test_object_id_must_match_algolia_map_key(self) -> None:
        row = dict(self.offer_map["2052"])
        row["objectID"] = "different"
        with self.assertRaisesRegex(ValueError, "objectID/map-key mismatch"):
            parse_aldi_nord_html(
                _html_with_offer_map({"2052": row}),
                self.context,
            )

    def test_zero_valid_offers_is_rejected(self) -> None:
        only_unpriced = {"1042929": self.offer_map["1042929"]}
        with self.assertRaisesRegex(ValueError, "zero valid structured offers"):
            parse_aldi_nord_html(
                _html_with_offer_map(only_unpriced),
                self.context,
            )


if __name__ == "__main__":
    unittest.main()
