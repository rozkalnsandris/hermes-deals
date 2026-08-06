from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.current_deals_fast_route import (
    _OfferMeta,
    _availability_state,
    _clear_current_deals_cache,
    fast_current_deals,
)
from app.current_deals_route_installer import installed_fast_current_deals
from app.main import app


class _Rows(list):
    def all(self):
        return list(self)


class _FakeDb:
    def execute(self, _statement):
        return _Rows()


def _deal(
    *,
    source_offer_id: str,
    valid_from: date,
    valid_until: date,
    collected_at: datetime | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_store_name=None,
        source_offer_id=source_offer_id,
        product_name_raw=f"Product {source_offer_id}",
        brand_raw="Brand",
        description_raw=None,
        package_text_raw="1 Packung",
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
        valid_from=valid_from,
        valid_until=valid_until,
        app_valid_from=None,
        app_valid_until=None,
        source_url="https://example.test/deal",
        source_image_url=None,
        collected_at=collected_at
        or datetime(2026, 8, 5, 8, tzinfo=timezone.utc),
    )


def _call(db, *, view: str = "current"):
    return fast_current_deals(
        as_of=date(2026, 8, 6),
        q=None,
        retailer=None,
        view=view,
        app_only=False,
        coupon_only=False,
        discount_only=False,
        image_only=False,
        sort="name",
        offset=0,
        limit=250,
        db=db,
    )


def test_fast_route_replaces_legacy_http_registration() -> None:
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/deals/current"
    ]

    assert len(routes) == 1
    assert routes[0].endpoint is installed_fast_current_deals


def test_availability_state_preserves_current_and_upcoming_windows() -> None:
    current = _OfferMeta(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_offer_id="current",
        collected_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
        app_price_eur=None,
        app_valid_from=None,
        app_valid_until=None,
    )
    upcoming = _OfferMeta(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_offer_id="upcoming",
        collected_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        valid_from=date(2026, 8, 7),
        valid_until=date(2026, 8, 9),
        app_price_eur=None,
        app_valid_from=None,
        app_valid_until=None,
    )

    assert _availability_state(current, date(2026, 8, 6)) == "current"
    assert _availability_state(upcoming, date(2026, 8, 6)) == "upcoming"


def test_fast_route_keeps_counts_and_caches_repeat_view() -> None:
    _clear_current_deals_cache()
    current = _deal(
        source_offer_id="current",
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
    )
    upcoming = _deal(
        source_offer_id="upcoming",
        valid_from=date(2026, 8, 7),
        valid_until=date(2026, 8, 9),
    )

    with patch(
        "app.current_deals_fast_route._load_newest_state_rows",
        return_value=[("current", current), ("upcoming", upcoming)],
    ) as loader:
        first = _call(_FakeDb())
        second = _call(_FakeDb())

    assert loader.call_count == 1
    assert first.available_count == 1
    assert first.count == 1
    assert first.deals[0].source_offer_id == "current"
    assert first.availability_counts.current == 1
    assert first.availability_counts.upcoming == 1
    assert second == first


def test_upcoming_view_returns_only_upcoming_rows() -> None:
    _clear_current_deals_cache()
    current = _deal(
        source_offer_id="current",
        valid_from=date(2026, 8, 6),
        valid_until=date(2026, 8, 8),
    )
    upcoming = _deal(
        source_offer_id="upcoming",
        valid_from=date(2026, 8, 7),
        valid_until=date(2026, 8, 9),
    )

    with patch(
        "app.current_deals_fast_route._load_newest_state_rows",
        return_value=[("current", current), ("upcoming", upcoming)],
    ):
        payload = _call(_FakeDb(), view="upcoming")

    assert payload.available_count == 1
    assert payload.deals[0].source_offer_id == "upcoming"
