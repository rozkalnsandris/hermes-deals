from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
import unittest

from app.aldi_nord_daily_special import (
    AldiNordDailySpecialContext,
    AldiNordDailySpecialError,
    cached_aldi_nord_daily_specials,
    extract_aldi_nord_daily_specials,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "aldi_nord_daily_special_20260804.html"
)
SOURCE_URL = "https://www.aldi-nord.de/angebote.html"
SNAPSHOT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _context() -> AldiNordDailySpecialContext:
    return AldiNordDailySpecialContext(
        snapshot_id=SNAPSHOT_ID,
        snapshot_sha256=sha256(FIXTURE.read_bytes()).hexdigest(),
        source_url=SOURCE_URL,
        collected_at=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
    )


def _source_html(
    *,
    short_title: str = "Nur Sa. 8.8.",
    product_valid_until: str = "2026-08-08",
) -> str:
    product = {
        "objectID": "42",
        "name": "Testprodukt",
        "brandName": "Testmarke",
        "salesUnit": "250-g-Packung",
        "currentPrice": {"priceValue": 1.49},
        "promotionPrices": [
            {
                "priceValue": 1.49,
                "validFromLocalDate": "2026-08-08",
                "validUntilLocalDate": product_valid_until,
            }
        ],
        "assets": [],
    }
    api_data = [
        [
            "OFFER_GET",
            {
                "res": {
                    "algoliaDataMap": {"42": product},
                    "categories": [
                        {
                            "title": "Aktion Sa. 8.8.",
                            "shortTitle": short_title,
                            "startDate": "2026-08-08",
                            "endDate": "2026-08-08",
                            "content": [
                                {
                                    "title": "ALDI Sparsamstag",
                                    "productIds": ["42"],
                                }
                            ],
                        }
                    ],
                }
            },
        ]
    ]
    payload = {"props": {"pageProps": {"apiData": json.dumps(api_data)}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></html>"
    )


class AldiNordDailySpecialTest(unittest.TestCase):
    def test_current_official_fixture_has_five_complete_daily_products(self) -> None:
        offers = extract_aldi_nord_daily_specials(FIXTURE.read_bytes(), _context())

        self.assertEqual(
            [offer.source_offer_id for offer in offers],
            [
                "aldi_nord:1004700:2026-08-08",
                "aldi_nord:10249000001:2026-08-08",
                "aldi_nord:1044330:2026-08-08",
                "aldi_nord:72530000001:2026-08-08",
                "aldi_nord:8078:2026-08-08",
            ],
        )
        self.assertTrue(
            all(
                offer.valid_from.isoformat() == "2026-08-08"
                and offer.valid_until.isoformat() == "2026-08-08"
                for offer in offers
            )
        )
        self.assertTrue(all(offer.package_text_raw for offer in offers))
        self.assertTrue(
            all(
                offer.raw_payload["special_source_text"]
                == "Aktion Sa. 8.8. | Nur Sa. 8.8. | ALDI Sparsamstag"
                for offer in offers
            )
        )

    def test_current_fixture_omits_conflicting_and_duplicate_source_objects(self) -> None:
        offers = extract_aldi_nord_daily_specials(FIXTURE.read_bytes(), _context())
        source_objects = {
            offer.raw_payload["source_object_id"] for offer in offers
        }

        self.assertNotIn("1013628", source_objects)
        self.assertNotIn("1017095", source_objects)
        self.assertIn("1004700", source_objects)

    def test_equal_dates_without_explicit_daily_label_are_not_daily_specials(self) -> None:
        offers = extract_aldi_nord_daily_specials(
            _source_html(short_title="Aktion Sa. 8.8."),
            _context(),
        )

        self.assertEqual(offers, ())

    def test_explicit_daily_group_rejects_product_date_mismatch(self) -> None:
        with self.assertRaisesRegex(
            AldiNordDailySpecialError,
            "no complete product evidence",
        ):
            extract_aldi_nord_daily_specials(
                _source_html(product_valid_until="2027-08-08"),
                _context(),
            )

    def test_malformed_explicit_daily_label_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            AldiNordDailySpecialError,
            "not an exact dated one-day label",
        ):
            extract_aldi_nord_daily_specials(
                _source_html(short_title="Nur Samstag"),
                _context(),
            )

    def test_official_source_url_is_required(self) -> None:
        invalid_context = AldiNordDailySpecialContext(
            snapshot_id=SNAPSHOT_ID,
            snapshot_sha256="a" * 64,
            source_url="https://www.aldi-sued.de/angebote.html",
            collected_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(AldiNordDailySpecialError, "official"):
            extract_aldi_nord_daily_specials(_source_html(), invalid_context)

    def test_snapshot_sha_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aldi.html"
            path.write_bytes(FIXTURE.read_bytes())
            cached_aldi_nord_daily_specials.cache_clear()
            with self.assertRaisesRegex(AldiNordDailySpecialError, "SHA mismatch"):
                cached_aldi_nord_daily_specials(
                    str(SNAPSHOT_ID),
                    str(path),
                    "0" * 64,
                    SOURCE_URL,
                    SOURCE_URL,
                    "2026-08-04T12:00:00+00:00",
                )
            cached_aldi_nord_daily_specials.cache_clear()

    def test_offline_replay_and_source_ids_are_deterministic(self) -> None:
        first = extract_aldi_nord_daily_specials(FIXTURE.read_bytes(), _context())
        second = extract_aldi_nord_daily_specials(FIXTURE.read_bytes(), _context())

        self.assertEqual(
            [offer.source_offer_id for offer in first],
            [offer.source_offer_id for offer in second],
        )
        self.assertEqual(
            [offer.raw_payload for offer in first],
            [offer.raw_payload for offer in second],
        )


if __name__ == "__main__":
    unittest.main()
