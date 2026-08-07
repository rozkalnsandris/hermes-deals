from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import unittest

from app.main import app
from app.weekly_special_api import (
    WeeklyDayOut,
    WeeklyDealOut,
    WeeklySpecialsOut,
    _clear_weekly_cache,
    _normalize_ui_payload,
    weekly_specials_ui,
)


class _FakeBind:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()


class _FakeDb:
    def get_bind(self):
        return _FakeBind()


def _deal() -> WeeklyDealOut:
    return WeeklyDealOut(
        offer_candidate_id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_store_name="Lidl Dortmund",
        source_offer_id="ui-weekly-test",
        product_name_raw="Test product",
        brand_raw="Test",
        package_text_raw="500 g",
        price_eur=Decimal("1.99"),
        regular_price_eur=Decimal("2.49"),
        unit_price_eur=None,
        unit_label=None,
        pricing_mode="fixed_package",
        regular_unit_price_eur=None,
        example_weight_g=None,
        discount_percent=Decimal("20"),
        app_price_eur=None,
        requires_app=False,
        coupon_required=False,
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
        app_valid_from=None,
        app_valid_until=None,
        base_price_current=True,
        app_price_current=False,
        source_url="https://example.test/deal",
        source_image_url=None,
        collected_at=datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
        canonical_product_id=None,
        canonical_comparable=False,
        is_daily_special=False,
        special_valid_on=None,
        special_confidence=None,
        deposit_eur=None,
    )


def _payload() -> WeeklySpecialsOut:
    deal = _deal()
    days = []
    for offset, day in enumerate(
        (
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
            date(2026, 8, 6),
            date(2026, 8, 7),
            date(2026, 8, 8),
            date(2026, 8, 9),
        )
    ):
        if 3 <= offset <= 5:
            day_deal = deal.model_copy(
                update={"base_price_current": offset <= 5}
            )
            deals = [day_deal]
        else:
            deals = []
        days.append(WeeklyDayOut(date=day, deals=deals))
    return WeeklySpecialsOut(
        week_start=date(2026, 8, 3),
        week_end=date(2026, 8, 9),
        timezone="Europe/Berlin",
        count=3,
        source_contract=(
            "single_week_query_short_periods_plus_explicit_immutable_daily_evidence"
        ),
        days=days,
    )


class WeeklySpecialUiApiTest(unittest.TestCase):
    def setUp(self) -> None:
        _clear_weekly_cache()

    def test_ui_route_is_registered_without_replacing_legacy_route(self) -> None:
        paths = app.openapi().get("paths", {})
        self.assertIn("/api/v1/deals/weekly-specials", paths)
        self.assertIn("/api/v1/deals/weekly-specials/ui", paths)
        self.assertNotIn("/ui/weekly-payload-bridge.js", paths)

    def test_normalization_stores_each_deal_once_and_preserves_day_entries(self) -> None:
        normalized = _normalize_ui_payload(_payload())

        self.assertEqual(normalized.ui_contract, "normalized_unique_deals_by_id_v1")
        self.assertEqual(normalized.count, 3)
        self.assertEqual(len(normalized.deals), 1)
        self.assertEqual(
            sum(len(day.deal_ids) for day in normalized.days),
            3,
        )
        deal_id = normalized.deals[0].offer_candidate_id
        active_ids = [
            day.deal_ids[0]
            for day in normalized.days
            if day.deal_ids
        ]
        self.assertEqual(active_ids, [deal_id, deal_id, deal_id])
        self.assertEqual(normalized.deals[0].source_store_name, "Lidl Dortmund")

    def test_ui_json_omits_optional_nulls_but_preserves_false_flags(self) -> None:
        normalized = _normalize_ui_payload(_payload())
        body = json.loads(normalized.model_dump_json(exclude_none=True))
        deal = body["deals"][0]

        self.assertNotIn("source_image_url", deal)
        self.assertNotIn("app_price_eur", deal)
        self.assertFalse(deal["canonical_comparable"])
        self.assertFalse(deal["is_daily_special"])
        self.assertEqual(deal["source_store_name"], "Lidl Dortmund")

    def test_endpoint_builds_once_then_serves_ui_memory_cache(self) -> None:
        request = SimpleNamespace(headers={})
        payload = _payload()
        with patch(
            "app.weekly_special_api._build_payload",
            return_value=payload,
        ) as build:
            first = weekly_specials_ui(
                request=request,
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )
            second = weekly_specials_ui(
                request=request,
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(first.headers["x-hermes-weekly-cache"], "MISS")
        self.assertEqual(second.headers["x-hermes-weekly-cache"], "HIT")
        body = json.loads(second.body)
        self.assertEqual(body["ui_contract"], "normalized_unique_deals_by_id_v1")
        self.assertEqual(len(body["deals"]), 1)
        self.assertEqual(
            sum(len(day["deal_ids"]) for day in body["days"]),
            body["count"],
        )

    def test_matching_ui_etag_returns_304_without_body(self) -> None:
        payload = _payload()
        with patch(
            "app.weekly_special_api._build_payload",
            return_value=payload,
        ):
            first = weekly_specials_ui(
                request=SimpleNamespace(headers={}),
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )
            second = weekly_specials_ui(
                request=SimpleNamespace(
                    headers={"if-none-match": first.headers["etag"]}
                ),
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )

        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.body, b"")
        self.assertEqual(second.headers["x-hermes-weekly-cache"], "HIT")
        self.assertIn(
            "stale-while-revalidate=300",
            second.headers["cache-control"],
        )


if __name__ == "__main__":
    unittest.main()
