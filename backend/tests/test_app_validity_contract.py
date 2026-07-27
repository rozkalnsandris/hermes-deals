from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.schemas import OfferCandidate, SourceChain


class AppValidityContractTest(unittest.TestCase):
    def candidate(self, **overrides) -> OfferCandidate:
        payload = {
            "source_chain": SourceChain.LIDL,
            "source_store_external_id": "DE06664",
            "source_store_name": "Lidl",
            "source_offer_id": "test-offer",
            "product_name_raw": "Test offer",
            "price_eur": Decimal("9.99"),
            "app_price_eur": Decimal("7.99"),
            "requires_app": True,
            "coupon_required": False,
            "valid_from": date(2026, 7, 27),
            "valid_until": date(2026, 8, 1),
            "app_valid_from": date(2026, 7, 27),
            "app_valid_until": date(2026, 8, 2),
            "source_url": "https://example.invalid/flyer.pdf",
            "snapshot_id": uuid4(),
            "collected_at": datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
            "parser_version": "test-app-validity",
            "raw_payload": {},
        }
        payload.update(overrides)
        return OfferCandidate(**payload)

    def test_app_validity_extension_is_valid(self) -> None:
        row = self.candidate()
        self.assertEqual(row.valid_until, date(2026, 8, 1))
        self.assertEqual(row.app_valid_until, date(2026, 8, 2))

    def test_app_validity_requires_complete_pair(self) -> None:
        with self.assertRaises(ValidationError):
            self.candidate(app_valid_until=None)

    def test_app_validity_order_is_validated(self) -> None:
        with self.assertRaises(ValidationError):
            self.candidate(
                app_valid_from=date(2026, 8, 2),
                app_valid_until=date(2026, 8, 1),
            )

    def test_app_validity_requires_app_price(self) -> None:
        with self.assertRaises(ValidationError):
            self.candidate(app_price_eur=None)


if __name__ == "__main__":
    unittest.main()
