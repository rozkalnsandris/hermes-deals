from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import deals_ui
from app.db import get_db


class _FakeDb:
    pass


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(deals_ui.router)
    app.dependency_overrides[get_db] = lambda: _FakeDb()
    return TestClient(app)


def _deal(name: str, offer_id: str):
    return SimpleNamespace(
        source_chain="lidl",
        source_store_name="Lidl Dortmund",
        source_offer_id=offer_id,
        product_name_raw=name,
        brand_raw="Brand",
        package_text_raw="1 Packung",
        price_eur=Decimal("1.49"),
        regular_price_eur=Decimal("1.99"),
        unit_price_eur=None,
        unit_label=None,
        discount_percent=Decimal("25"),
        app_price_eur=None,
        requires_app=False,
        coupon_required=False,
        canonical_comparable=False,
    )


def _payload(*, offset: int = 0, limit: int = 250, available: int = 2, deals=None):
    rows = deals if deals is not None else [_deal("Apple", "a"), _deal("Banana", "b")]
    return SimpleNamespace(
        as_of=date(2026, 9, 30),
        timezone="Europe/Berlin",
        available_count=available,
        offset=offset,
        limit=limit,
        count=len(rows),
        deals=rows,
    )


def test_full_page_is_server_rendered_no_js_fallback_and_autoescaped() -> None:
    payload = _payload(deals=[_deal("<script>alert(1)</script>", "x")])
    with patch("app.deals_ui._load_deals", return_value=payload):
        response = _client().get("/ui/deals")

    assert response.status_code == 200
    assert "<!doctype html>" in response.text
    assert 'action="/ui/deals" method="get"' in response.text
    assert 'src="/ui/deals/assets/htmx.min.js"' in response.text
    assert "https://unpkg.com" not in response.text
    assert "https://cdn.jsdelivr.net" not in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert response.headers["vary"] == "HX-Request"
    assert response.headers["cache-control"] == "private, no-store"


def test_all_current_deals_query_semantics_are_forwarded() -> None:
    payload = _payload(offset=4, limit=2, available=6)
    url = (
        "/ui/deals?as_of=2026-09-30&q=milk&retailer=lidl&view=upcoming"
        "&app_only=true&coupon_only=true&discount_only=true&image_only=true"
        "&sort=price_asc&offset=4&limit=2"
    )
    with patch("app.deals_ui._load_deals", return_value=payload) as loader:
        response = _client().get(url)

    assert response.status_code == 200
    assert loader.call_args.kwargs == {
        "db": loader.call_args.kwargs["db"],
        "as_of": date(2026, 9, 30),
        "q": "milk",
        "retailer": "lidl",
        "view": "upcoming",
        "app_only": True,
        "coupon_only": True,
        "discount_only": True,
        "image_only": True,
        "sort": "price_asc",
        "offset": 4,
        "limit": 2,
    }


def test_htmx_request_returns_fragment_and_canonical_push_url() -> None:
    with patch("app.deals_ui._load_deals", return_value=_payload()):
        response = _client().get(
            "/ui/deals?q=milk",
            headers={"HX-Request": "true"},
        )

    assert response.status_code == 200
    assert "<!doctype html>" not in response.text
    assert 'id="deal-results"' in response.text
    assert response.headers["hx-push-url"] == "/ui/deals?q=milk"
    assert response.headers["vary"] == "HX-Request"


def test_normal_get_redirects_to_stable_canonical_query() -> None:
    response = _client().get(
        "/ui/deals?q=%20milk%20&retailer=LIDL&view=current&app_only=false"
        "&coupon_only=false&discount_only=false&image_only=false&sort=name"
        "&offset=0&limit=250",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/ui/deals?q=milk&retailer=lidl"
    assert response.headers["vary"] == "HX-Request"


def test_pagination_preserves_service_order_and_query_state() -> None:
    payload = _payload(
        offset=2,
        limit=2,
        available=5,
        deals=[_deal("Zulu", "z"), _deal("Alpha", "a")],
    )
    with patch("app.deals_ui._load_deals", return_value=payload):
        response = _client().get("/ui/deals?q=milk&offset=2&limit=2")

    assert response.status_code == 200
    assert response.text.index("Zulu") < response.text.index("Alpha")
    assert 'href="/ui/deals?q=milk&amp;limit=2"' in response.text
    assert 'href="/ui/deals?q=milk&amp;offset=4&amp;limit=2"' in response.text


def test_release_image_fetches_pinned_verified_htmx() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "fa978b24e75fb03c137bf2cdae4fef0e711cf8a1" in dockerfile
    assert "e6b8394acb5cda3281a68b4078775ec348d8eafc" in dockerfile
    assert "raw.githubusercontent.com/bigskysoftware/htmx/" in dockerfile
    assert "/app/app/ui_deals/assets/htmx.min.js" in dockerfile
