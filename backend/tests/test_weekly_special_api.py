from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import unittest

from fastapi import HTTPException

from app.main import app
from app.models import OfferCandidateRecord
from app.weekly_special_api import (
    _clear_weekly_cache,
    _ordinary_days,
    _qualifying_windows,
    weekly_specials,
)


class _FakeBind:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()


class _FakeDb:
    def get_bind(self):
        return _FakeBind()


def _row(
    *,
    source_chain: str = "lidl",
    source_offer_id: str = "weekly-test",
    valid_from: date = date(2026, 8, 6),
    valid_until: date = date(2026, 8, 8),
    collected_at: datetime = datetime(
        2026,
        8,
        5,
        8,
        tzinfo=timezone.utc,
    ),
) -> OfferCandidateRecord:
    return OfferCandidateRecord(
        id=uuid4(),
        source_chain=source_chain,
        source_store_external_id=None,
        source_store_name=None,
        source_offer_id=source_offer_id,
        product_name_raw="Test product",
        brand_raw="Test",
        description_raw=None,
        package_text_raw="1 Packung",
        price_eur=Decimal("1.99"),
        regular_price_eur=Decimal("2.49"),
        unit_price_eur=None,
        unit_label=None,
        pricing_mode="fixed_package",
        regular_unit_price_eur=None,
        example_weight_g=None,
        discount_percent=20,
        app_price_eur=None,
        requires_app=False,
        coupon_required=False,
        valid_from=valid_from,
        valid_until=valid_until,
        app_valid_from=None,
        app_valid_until=None,
        source_url="https://example.test/deal",
        source_image_url=None,
        snapshot_id=uuid4(),
        collected_at=collected_at,
        parser_version="test",
        raw_payload={},
    )


class WeeklySpecialApiTest(unittest.TestCase):
    def setUp(self) -> None:
        _clear_weekly_cache()

    def test_route_is_registered(self) -> None:
        self.assertIn(
            "/api/v1/deals/weekly-specials",
            app.openapi().get("paths", {}),
        )

    def test_only_short_non_netto_windows_qualify(self) -> None:
        short = _row()
        full_week = _row(
            source_offer_id="full-week",
            valid_from=date(2026, 8, 3),
            valid_until=date(2026, 8, 9),
        )
        netto = _row(source_chain="netto")

        self.assertEqual(len(_qualifying_windows(short)), 1)
        self.assertEqual(_qualifying_windows(full_week), ())
        self.assertEqual(_qualifying_windows(netto), ())

    def test_one_row_is_reused_for_each_active_day(self) -> None:
        row = _row()
        days = _ordinary_days([row], date(2026, 8, 3))

        self.assertEqual(len(days[date(2026, 8, 5)]), 0)
        self.assertEqual(len(days[date(2026, 8, 6)]), 1)
        self.assertEqual(len(days[date(2026, 8, 7)]), 1)
        self.assertEqual(len(days[date(2026, 8, 8)]), 1)
        self.assertEqual(len(days[date(2026, 8, 9)]), 0)

    def test_newest_stable_identity_wins_per_day(self) -> None:
        older = _row(
            collected_at=datetime(
                2026,
                8,
                5,
                7,
                tzinfo=timezone.utc,
            ),
        )
        newer = _row(
            collected_at=datetime(
                2026,
                8,
                5,
                9,
                tzinfo=timezone.utc,
            ),
        )
        days = _ordinary_days([older, newer], date(2026, 8, 3))

        self.assertEqual(
            days[date(2026, 8, 6)][0].offer_candidate_id,
            newer.id,
        )

    def test_endpoint_builds_once_then_serves_memory_cache(self) -> None:
        request = SimpleNamespace(headers={})
        ordinary = _row()
        with (
            patch(
                "app.weekly_special_api._query_week_rows",
                return_value=[ordinary],
            ) as query,
            patch(
                "app.weekly_special_api._explicit_daily_specials",
                return_value={
                    day: []
                    for day in (
                        date(2026, 8, 3),
                        date(2026, 8, 4),
                        date(2026, 8, 5),
                        date(2026, 8, 6),
                        date(2026, 8, 7),
                        date(2026, 8, 8),
                        date(2026, 8, 9),
                    )
                },
            ),
        ):
            first = weekly_specials(
                request=request,
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )
            second = weekly_specials(
                request=request,
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(query.call_count, 1)
        self.assertEqual(first.headers["x-hermes-weekly-cache"], "MISS")
        self.assertEqual(second.headers["x-hermes-weekly-cache"], "HIT")
        payload = json.loads(second.body)
        self.assertEqual(payload["week_start"], "2026-08-03")
        self.assertEqual(len(payload["days"]), 7)

    def test_matching_etag_returns_304_without_body(self) -> None:
        ordinary = _row()
        empty_explicit = {
            day: []
            for day in (
                date(2026, 8, 3),
                date(2026, 8, 4),
                date(2026, 8, 5),
                date(2026, 8, 6),
                date(2026, 8, 7),
                date(2026, 8, 8),
                date(2026, 8, 9),
            )
        }
        with (
            patch(
                "app.weekly_special_api._query_week_rows",
                return_value=[ordinary],
            ),
            patch(
                "app.weekly_special_api._explicit_daily_specials",
                return_value=empty_explicit,
            ),
        ):
            first = weekly_specials(
                request=SimpleNamespace(headers={}),
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )
            second = weekly_specials(
                request=SimpleNamespace(
                    headers={"if-none-match": first.headers["etag"]}
                ),
                week_start=date(2026, 8, 3),
                db=_FakeDb(),
            )

        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.body, b"")
        self.assertIn("stale-while-revalidate=300", second.headers["cache-control"])
        self.assertIn("weekly;dur=", second.headers["server-timing"])

    def test_non_monday_week_start_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            weekly_specials(
                request=SimpleNamespace(headers={}),
                week_start=date(2026, 8, 4),
                db=_FakeDb(),
            )
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
