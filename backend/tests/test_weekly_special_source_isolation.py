from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

import app.weekly_special_api as weekly_api
import app.weekly_special_runtime_patch as runtime_patch
from app.models import OfferCandidateRecord


class _FakeBind:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()


class _FakeDb:
    def get_bind(self):
        return _FakeBind()


def _ordinary_row() -> OfferCandidateRecord:
    return OfferCandidateRecord(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_store_name=None,
        source_offer_id="source-isolation-lidl",
        product_name_raw="Lidl short offer",
        brand_raw="Lidl",
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
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
        app_valid_from=None,
        app_valid_until=None,
        source_url="https://example.test/lidl",
        source_image_url=None,
        snapshot_id=uuid4(),
        collected_at=datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
        parser_version="test",
        raw_payload={},
    )


def test_runtime_patch_is_installed_before_route_use() -> None:
    assert weekly_api._source_isolation_patch_installed is True
    assert (
        weekly_api._explicit_daily_specials
        is runtime_patch.isolated_explicit_daily_specials
    )


def test_unavailable_immutable_sources_return_an_empty_evidence_layer() -> None:
    unavailable = HTTPException(status_code=503, detail="missing evidence")
    with (
        patch.object(
            runtime_patch.daily_api,
            "_latest_snapshot",
            side_effect=unavailable,
        ),
        patch.object(
            runtime_patch.daily_api,
            "_latest_aldi_nord_snapshot",
            side_effect=unavailable,
        ),
    ):
        result = runtime_patch.isolated_explicit_daily_specials(
            _FakeDb(),
            date(2026, 8, 3),
            date(2026, 8, 9),
        )

    assert list(result) == [
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        date(2026, 8, 6),
        date(2026, 8, 7),
        date(2026, 8, 8),
        date(2026, 8, 9),
    ]
    assert all(rows == [] for rows in result.values())


def test_source_failure_does_not_discard_valid_ordinary_week_rows() -> None:
    weekly_api._clear_weekly_cache()
    with (
        patch.object(
            weekly_api,
            "_query_week_rows",
            return_value=[_ordinary_row()],
        ),
        patch.object(
            runtime_patch,
            "_netto_offers_for_day",
            return_value=(),
        ),
        patch.object(runtime_patch, "_aldi_offers", return_value=()),
    ):
        response = weekly_api.weekly_specials(
            request=SimpleNamespace(headers={}),
            week_start=date(2026, 8, 3),
            db=_FakeDb(),
        )

    assert response.status_code == 200
    assert b"Lidl short offer" in response.body
    assert response.headers["x-hermes-weekly-cache"] == "MISS"
