from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app import main
from app.current_deals_service import build_current_deals, load_python_ranked_state_rows


class _Rows(list):
    def all(self):
        return list(self)


class _FakeDb:
    def execute(self, _statement):
        return _Rows()


def _deal(*, source_offer_id: str, name: str, price: str):
    return SimpleNamespace(
        id=uuid4(),
        source_chain="lidl",
        source_store_external_id=None,
        source_store_name="Lidl Dortmund",
        source_offer_id=source_offer_id,
        product_name_raw=name,
        brand_raw="Brand",
        description_raw=None,
        package_text_raw="1 Packung",
        price_eur=Decimal(price),
        regular_price_eur=Decimal("2.99"),
        unit_price_eur=None,
        unit_label=None,
        pricing_mode="fixed_package",
        regular_unit_price_eur=None,
        example_weight_g=None,
        discount_percent=Decimal("10"),
        app_price_eur=None,
        requires_app=False,
        coupon_required=False,
        valid_from=date(2026, 9, 21),
        valid_until=date(2026, 9, 27),
        app_valid_from=None,
        app_valid_until=None,
        source_url="https://example.test/deal",
        source_image_url=None,
        collected_at=datetime(2026, 9, 21, 8, tzinfo=timezone.utc),
    )


def test_shared_service_uses_injected_rows_without_fastapi_route_state() -> None:
    rows = [
        ("current", _deal(source_offer_id="b", name="Banana", price="1.99")),
        ("current", _deal(source_offer_id="a", name="Apple", price="1.49")),
    ]
    calls = []

    def loader(db, effective_date):
        calls.append((db, effective_date))
        return rows

    db = _FakeDb()
    payload = build_current_deals(
        db=db,
        effective_date=date(2026, 9, 21),
        q=None,
        retailer=None,
        view="current",
        app_only=False,
        coupon_only=False,
        discount_only=False,
        image_only=False,
        sort="price_asc",
        offset=0,
        limit=10,
        state_row_loader=loader,
    )

    assert calls == [(db, date(2026, 9, 21))]
    assert [deal.source_offer_id for deal in payload.deals] == ["a", "b"]
    assert payload.available_count == 2
    assert payload.retailer_counts == {"lidl": 2}


def test_main_current_deals_delegates_to_shared_service() -> None:
    sentinel = object()
    with patch("app.main.build_current_deals", return_value=sentinel) as service:
        result = main.current_deals(
            as_of=date(2026, 9, 21),
            q=None,
            retailer=None,
            view="current",
            app_only=False,
            coupon_only=False,
            discount_only=False,
            image_only=False,
            sort="name",
            offset=0,
            limit=250,
            db=_FakeDb(),
        )

    assert result is sentinel
    assert service.call_args.kwargs["state_row_loader"] is load_python_ranked_state_rows
