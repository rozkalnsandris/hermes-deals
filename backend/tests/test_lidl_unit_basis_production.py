from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

from app.review_queue import _build_offer
from app.schemas import OfferCandidate, SourceChain


def base_offer(**updates):
    data = {
        "source_chain": SourceChain.LIDL,
        "source_store_external_id": None,
        "source_store_name": "Lidl",
        "source_offer_id": "fixture",
        "product_name_raw": "Fixture",
        "brand_raw": None,
        "description_raw": None,
        "package_text_raw": "100 g",
        "price_eur": Decimal("1.00"),
        "regular_price_eur": None,
        "unit_price_eur": None,
        "unit_label": None,
        "pricing_mode": None,
        "regular_unit_price_eur": None,
        "example_weight_g": None,
        "discount_percent": None,
        "app_price_eur": None,
        "requires_app": False,
        "coupon_required": False,
        "valid_from": date(2026, 8, 6),
        "valid_until": date(2026, 8, 8),
        "app_valid_from": None,
        "app_valid_until": None,
        "source_url": "https://example.test/flyer",
        "source_image_url": None,
        "snapshot_id": uuid.uuid4(),
        "collected_at": datetime.now(timezone.utc),
        "parser_version": "fixture",
        "raw_payload": {},
    }
    data.update(updates)
    return OfferCandidate(**data)


class LidlUnitBasisProductionTest(unittest.TestCase):
    def test_legacy_offer_contract_stays_valid(self):
        self.assertIsNone(base_offer().pricing_mode)

    def test_unit_price_only_requires_unit_fields(self):
        with self.assertRaisesRegex(ValueError, "requires unit_price_eur"):
            base_offer(pricing_mode="unit_price_only")

    def test_example_total_requires_example_weight(self):
        with self.assertRaisesRegex(ValueError, "requires example_weight_g"):
            base_offer(
                pricing_mode="example_total_plus_unit",
                unit_price_eur=Decimal("9.99"),
                unit_label="kg",
            )

    def test_app_example_requires_app_flag(self):
        with self.assertRaisesRegex(ValueError, "requires requires_app=true"):
            base_offer(
                pricing_mode="app_example_total_plus_unit",
                unit_price_eur=Decimal("17.90"),
                unit_label="kg",
                example_weight_g=Decimal("220"),
            )

    def test_valid_example_total_contract(self):
        offer = base_offer(
            price_eur=Decimal("5.60"),
            pricing_mode="example_total_plus_unit",
            unit_price_eur=Decimal("9.99"),
            unit_label="kg",
            example_weight_g=Decimal("560"),
        )
        self.assertEqual(offer.unit_price_eur, Decimal("9.99"))
        self.assertEqual(offer.example_weight_g, Decimal("560"))

    def test_review_approval_fails_closed_without_unit_basis_truth(self):
        item = SimpleNamespace(
            id=uuid.uuid4(),
            source_chain="lidl",
            source_flyer_key="fixture",
            source_row_key="row",
            page_number=1,
            parser_version="fixture",
            reason_codes=["variable_weight_requires_review"],
            original_payload={
                "scope": "in_scope",
                "channel": "physical_store",
                "product_name": "Variable fixture",
                "price_eur": "5.60",
                "valid_from": "2026-08-06",
                "valid_until": "2026-08-08",
            },
            corrected_payload={},
            provenance_json={},
        )
        snapshot = SimpleNamespace(
            id=uuid.uuid4(),
            source_url="https://example.test/source",
            final_url="https://example.test/final",
            collected_at=datetime.now(timezone.utc),
        )
        with self.assertRaisesRegex(
            ValueError,
            "requires explicit unit-basis pricing_mode",
        ):
            _build_offer(
                item=item,
                manual_snapshot=snapshot,
                original_snapshot=snapshot,
            )

    def test_review_and_family_ui_expose_unit_basis_controls(self):
        ui = Path(__file__).resolve().parents[1] / "app" / "ui"
        review = (ui / "review.html").read_text(encoding="utf-8")
        family = (ui / "index.html").read_text(encoding="utf-8")
        for token in (
            'id="f_pricing_mode"',
            'id="f_requires_app"',
            'field("f_unit","Vienības cena €"',
            'field("f_regular_unit","Parastā vienības cena €"',
            'field("f_example_weight","Piemēra svars g"',
        ):
            self.assertIn(token, review)
        self.assertIn("isUnitBasis", family)
        self.assertIn("Piemēra cena", family)
        self.assertIn("Cena pēc svara", family)


if __name__ == "__main__":
    unittest.main()
