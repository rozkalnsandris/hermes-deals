from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SNAPSHOT_ID = UUID("21111111-2222-4333-8444-555555555555")


class EdekaCampaignFreshnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = FIXTURE.read_text(encoding="utf-8")

    @staticmethod
    def _context(collected_at: datetime) -> EdekaParserContext:
        return EdekaParserContext(
            snapshot_id=SNAPSHOT_ID,
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=collected_at,
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def test_accepts_campaign_covering_collection_date(self) -> None:
        offers = parse_edeka_html(
            self.html,
            self._context(
                datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
            ),
        )

        self.assertEqual(len(offers), 2)
        self.assertTrue(
            all(str(offer.valid_from) == "2026-07-20" for offer in offers)
        )
        self.assertTrue(
            all(str(offer.valid_until) == "2026-07-25" for offer in offers)
        )
        self.assertTrue(
            all(
                "campaign_reference_date" not in offer.raw_payload
                for offer in offers
            )
        )

    def test_accepts_current_august_patzer_week(self) -> None:
        current_week = self.html.replace(
            "20.07.2026",
            "03.08.2026",
        ).replace(
            "25.07.2026",
            "08.08.2026",
        )

        offers = parse_edeka_html(
            current_week,
            self._context(
                datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
            ),
        )

        self.assertEqual(len(offers), 2)
        self.assertTrue(
            all(str(offer.valid_from) == "2026-08-03" for offer in offers)
        )
        self.assertTrue(
            all(str(offer.valid_until) == "2026-08-08" for offer in offers)
        )

    def test_rejects_stale_campaign_before_offer_write(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "refusing stale or future catalogue",
        ):
            parse_edeka_html(
                self.html,
                self._context(
                    datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
                ),
            )

    def test_rejects_future_campaign_before_offer_write(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "refusing stale or future catalogue",
        ):
            parse_edeka_html(
                self.html,
                self._context(
                    datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)
                ),
            )

    def test_rejects_implausibly_long_campaign(self) -> None:
        long_campaign = self.html.replace(
            "25.07.2026",
            "29.07.2026",
        )

        with self.assertRaisesRegex(ValueError, "implausibly long"):
            parse_edeka_html(
                long_campaign,
                self._context(
                    datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
                ),
            )

    def test_rejects_naive_collection_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            parse_edeka_html(
                self.html,
                self._context(datetime(2026, 7, 24, 12, 0)),
            )


if __name__ == "__main__":
    unittest.main()
