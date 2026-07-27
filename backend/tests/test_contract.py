from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from app.schemas import OfferCandidate, SourceChain


class OfferCandidateContractTest(unittest.TestCase):
    def make_offer(self, **overrides):
        payload = {
            "source_chain": SourceChain.NETTO,
            "product_name_raw": "Test Milch 1 l",
            "price_eur": Decimal("0.89"),
            "source_url": "https://example.invalid/offer",
            "snapshot_id": uuid4(),
            "collected_at": datetime.now(timezone.utc),
            "parser_version": "netto-v0",
        }
        payload.update(overrides)
        return OfferCandidate(**payload)

    def test_minimal_offer_is_valid(self):
        offer = self.make_offer()
        self.assertEqual(offer.price_eur, Decimal("0.89"))

    def test_negative_price_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_offer(price_eur=Decimal("-1.00"))

    def test_discount_over_100_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_offer(discount_percent=101)

    def test_valid_until_before_valid_from_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.make_offer(valid_from=date(2026, 7, 25), valid_until=date(2026, 7, 20))


if __name__ == "__main__":
    unittest.main()
