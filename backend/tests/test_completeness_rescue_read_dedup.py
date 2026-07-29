from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.completeness_rescue_read import (
    dedupe_completeness_rescue_publications,
)


def row(
    *,
    source_offer_id: str,
    price: str = "0.24",
    rescue: bool = False,
    collected_minute: int = 0,
):
    raw = {}
    if rescue:
        raw = {
            "price_basis": "completeness_rescue_review",
            "review_original_payload": {
                "completeness_rescue": {
                    "candidate_key": "fixture-gap",
                    "review_required": True,
                }
            },
        }
    return SimpleNamespace(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id="DE06664",
        source_offer_id=source_offer_id,
        product_name_raw="Buttercroissant",
        price_eur=Decimal(price),
        valid_from=date(2026, 8, 3),
        valid_until=date(2026, 8, 8),
        source_url="https://example.invalid/flyer",
        collected_at=datetime(
            2026, 7, 29, 12, collected_minute, tzinfo=timezone.utc
        ),
        raw_payload=raw,
    )


class CompletenessRescueReadDedupTest(unittest.TestCase):
    def test_rescue_publication_wins_exact_cross_identity_duplicate(self) -> None:
        parser=row(source_offer_id="corpus-row", collected_minute=1)
        rescue=row(
            source_offer_id="manual-review-row",
            rescue=True,
            collected_minute=2,
        )
        result=dedupe_completeness_rescue_publications(
            [("upcoming", parser), ("upcoming", rescue)]
        )
        self.assertEqual(len(result),1)
        self.assertIs(result[0][1],rescue)

    def test_different_price_is_not_merged(self) -> None:
        parser=row(source_offer_id="corpus-row", price="0.25")
        rescue=row(source_offer_id="manual-review-row", rescue=True)
        result=dedupe_completeness_rescue_publications(
            [("upcoming", parser), ("upcoming", rescue)]
        )
        self.assertEqual(len(result),2)


if __name__ == "__main__":
    unittest.main()
