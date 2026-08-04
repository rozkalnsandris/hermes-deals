from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID
import unittest

from fastapi import HTTPException

from app.aldi_nord_daily_special import AldiNordDailySpecialError
from app.netto_daily_special_api import (
    _latest_aldi_nord_snapshot,
    daily_specials,
)
from app.schemas import OfferCandidate, SourceChain


class _FakeBind:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()


class _FakeDb:
    def __init__(self, snapshot=None) -> None:
        self.snapshot = snapshot
        self.statements: list[str] = []

    def get_bind(self):
        return _FakeBind()

    def scalar(self, statement):
        self.statements.append(str(statement))
        return self.snapshot


def _daily_offer(
    chain: SourceChain,
    *,
    source_offer_id: str,
    product_name: str,
    price: str,
) -> OfferCandidate:
    special_date = date(2026, 8, 8)
    return OfferCandidate(
        source_chain=chain,
        source_offer_id=source_offer_id,
        product_name_raw=product_name,
        brand_raw="Testbrand",
        package_text_raw="250-g-Packung",
        price_eur=Decimal(price),
        regular_price_eur=None,
        unit_price_eur=None,
        unit_label=None,
        pricing_mode="fixed_package",
        discount_percent=None,
        requires_app=False,
        coupon_required=False,
        valid_from=special_date,
        valid_until=special_date,
        source_url="https://example.test/source",
        source_image_url=None,
        snapshot_id=UUID("11111111-1111-1111-1111-111111111111"),
        collected_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        parser_version="test-daily",
        raw_payload={
            "is_daily_special": True,
            "special_valid_on": special_date.isoformat(),
            "special_type": "explicit_test_daily",
            "special_source_text": "Nur Sa. 8.8.",
            "special_source_kind": "structured_source_object",
            "special_source_page": 0,
            "special_confidence": "high",
            "source_snapshot_sha256": "a" * 64,
            "bundle_quantity": None,
            "single_price_eur": None,
            "shadow_only": True,
            "db_write_eligible": False,
        },
    )


class MultiRetailerDailySpecialsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.netto_snapshot = SimpleNamespace(
            id=UUID("22222222-2222-2222-2222-222222222222"),
            snapshot_path="/tmp/netto-manifest.json",
            sha256="b" * 64,
            source_url="https://example.test/netto",
            final_url="https://example.test/netto-final",
            collected_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )
        self.aldi_snapshot = SimpleNamespace(
            id=UUID("33333333-3333-3333-3333-333333333333"),
            snapshot_path="/tmp/aldi.html",
            sha256="c" * 64,
            source_url="https://www.aldi-nord.de/angebote.html",
            final_url="https://www.aldi-nord.de/angebote.html",
            collected_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )

    def test_verified_retailers_aggregate_in_stable_order(self) -> None:
        netto = _daily_offer(
            SourceChain.NETTO,
            source_offer_id="netto:z",
            product_name="Zitrone",
            price="1.49",
        )
        aldi = _daily_offer(
            SourceChain.ALDI_NORD,
            source_offer_id="aldi:a",
            product_name="Apfel",
            price="0.95",
        )
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=self.netto_snapshot,
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=(netto,),
            ),
            patch(
                "app.netto_daily_special_api._latest_aldi_nord_snapshot",
                return_value=self.aldi_snapshot,
            ),
            patch(
                "app.netto_daily_special_api.cached_aldi_nord_daily_specials",
                return_value=(aldi,),
            ),
        ):
            result = daily_specials(as_of=date(2026, 8, 8), db=_FakeDb())

        self.assertEqual(result.retailer_counts, {"aldi_nord": 1, "netto": 1})
        self.assertEqual(
            [row.source_offer_id for row in result.deals],
            ["aldi:a", "netto:z"],
        )
        self.assertEqual(
            result.source_contract,
            "explicit_immutable_retailer_evidence_only",
        )

    def test_aldi_evidence_failure_is_an_explicit_503_not_partial_data(self) -> None:
        netto = _daily_offer(
            SourceChain.NETTO,
            source_offer_id="netto:verified",
            product_name="Milch",
            price="1.49",
        )
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=self.netto_snapshot,
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=(netto,),
            ),
            patch(
                "app.netto_daily_special_api._latest_aldi_nord_snapshot",
                return_value=self.aldi_snapshot,
            ),
            patch(
                "app.netto_daily_special_api.cached_aldi_nord_daily_specials",
                side_effect=AldiNordDailySpecialError("bad SHA"),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                daily_specials(as_of=date(2026, 8, 8), db=_FakeDb())

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("ALDI Nord", raised.exception.detail)

    def test_missing_declared_aldi_evidence_fails_closed(self) -> None:
        snapshot = SimpleNamespace(snapshot_path=None, sha256=None)
        with self.assertRaises(HTTPException) as raised:
            _latest_aldi_nord_snapshot(_FakeDb(snapshot))

        self.assertEqual(raised.exception.status_code, 503)

    def test_endpoint_performs_no_database_write(self) -> None:
        database = _FakeDb()
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=self.netto_snapshot,
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=(),
            ),
            patch(
                "app.netto_daily_special_api._latest_aldi_nord_snapshot",
                return_value=None,
            ),
        ):
            result = daily_specials(as_of=date(2026, 8, 8), db=database)

        self.assertEqual(result.count, 0)
        self.assertEqual(database.statements, [])


if __name__ == "__main__":
    unittest.main()
