from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, CanonicalProduct, OfferCandidateRecord, OfferProductLink, SourceSnapshot


@pytest.fixture
def data():
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield db, client
        app.dependency_overrides.clear()
    engine.dispose()


def offer(db, *, day=1, price="1.99", chain="lidl", store="store-a", sku="milk", **values):
    collected = datetime(2026, 9, day, 12, tzinfo=timezone.utc)
    snapshot = SourceSnapshot(source_chain=chain, source_url="https://example.invalid/source",
                              collected_at=collected, strategy_hint="test", success=True)
    db.add(snapshot)
    db.flush()
    fields = dict(source_chain=chain, source_store_external_id=store, source_offer_id=sku,
                  product_name_raw="Milk", brand_raw="Test", package_text_raw="1 l",
                  price_eur=Decimal(price), valid_from=date(2026, 9, 1), valid_until=date(2026, 9, 30),
                  collected_at=collected, snapshot_id=snapshot.id,
                  source_url="https://example.invalid/offer", parser_version="test")
    fields.update(values)
    row = OfferCandidateRecord(**fields)
    db.add(row)
    db.flush()
    return row


def product(db):
    row = CanonicalProduct(display_name="Test Milk", normalized_name="milk",
                           item_quantity_value=Decimal("1000"), item_quantity_unit="ml", pack_count=1)
    db.add(row)
    db.flush()
    return row


def link(db, row, canonical):
    # An existing explicit seed/reviewed link is authority, never auto-matching.
    db.add(OfferProductLink(offer_candidate_id=row.id, canonical_product_id=canonical.id,
                           link_method="reviewed-test", confidence=Decimal("1")))
    db.flush()


def get(client, row, **params):
    response = client.get(f"/api/v1/offers/{row.id}/price-intelligence",
                          params={"as_of": "2026-09-30", **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_unmapped_offer_has_source_history_without_claiming_comparison(data):
    db, client = data
    old = offer(db, day=1, price="2.19")
    current = offer(db, day=2)
    offer(db, day=3, store="other-store", price="0.01")
    offer(db, day=3, chain="netto", price="0.02")
    body = get(client, current)
    assert [row["price_eur"] for row in body["observations"]] == ["1.99", "2.19"]
    assert body["history_scope"] == "retailer_product"
    assert body["history_basis"] == "package"
    assert body["canonical_product_id"] is None
    assert body["comparison_status"] == "identity_not_reviewed"
    assert body["comparison_available"] is False
    assert body["observations"][1]["snapshot_id"] == str(old.snapshot_id)


@pytest.mark.parametrize("change", [
    {"package_text_raw": "750 ml"}, {"product_name_raw": "Cream"},
    {"brand_raw": "Other"}, {"requires_app": True}, {"coupon_required": True},
    {"pricing_mode": "unit_price_only", "unit_label": "l", "unit_price_eur": Decimal("2.00")},
])
def test_changed_identity_package_basis_or_conditions_start_new_series(data, change):
    db, client = data
    old = offer(db, day=1, **change)
    current = offer(db, day=2)
    link(db, old, product(db))
    body = get(client, current)
    assert len(body["observations"]) == 1
    assert body["canonical_product_id"] is None


@pytest.mark.parametrize("values", [{"package_text_raw": None}, {"sku": None}])
def test_unknown_package_or_source_id_does_not_infer_continuity(data, values):
    db, client = data
    offer(db, day=1, **values)
    current = offer(db, day=2, **values)
    assert len(get(client, current)["observations"]) == 1


def test_unit_history_uses_unit_price_and_keeps_app_requirements(data):
    db, client = data
    row = offer(db, pricing_mode="app_example_total_plus_unit", unit_label="kg",
                unit_price_eur=Decimal("4.99"), requires_app=True, coupon_required=True,
                app_price_eur=Decimal("2.50"), app_valid_from=date(2026, 9, 1),
                app_valid_until=date(2026, 9, 4))
    link(db, row, product(db))
    body = get(client, row)
    assert body["history_basis"] == "kg"
    assert Decimal(body["observations"][0]["comparison_price_eur"]) == Decimal("4.99")
    assert body["observations"][0]["requires_app"] is True
    assert body["observations"][0]["app_valid_until"] == "2026-09-04"
    assert body["comparison_status"] == "unsupported_price_basis"


def test_reviewed_identity_compares_current_compatible_stores(data):
    db, client = data
    a = offer(db, price="2.19")
    b = offer(db, chain="netto", price="1.89")
    canonical = product(db)
    link(db, a, canonical)
    link(db, b, canonical)
    current = offer(db, day=2, price="2.09")
    body = get(client, current)
    assert body["canonical_product_id"] == str(canonical.id)
    assert body["comparison_available"] is True
    assert body["lowest_price_eur"] == "1.89"
    assert body["price_spread_eur"] == "0.20"
    assert len(body["offers"]) == 2
    assert get(client, current, as_of="2026-10-01")["comparison_status"] == "no_current_offers"


def test_comparison_rejects_recycled_package_and_conditional_store(data):
    db, client = data
    a = offer(db)
    b = offer(db, chain="netto")
    conditional = offer(db, chain="edeka", requires_app=True, price="0.99")
    canonical = product(db)
    for row in (a, b, conditional):
        link(db, row, canonical)
    offer(db, day=2, chain="netto", package_text_raw="750 ml", price="0.89")
    body = get(client, a)
    assert body["comparison_status"] == "single_store"
    assert len(body["offers"]) == 1
    assert body["price_spread_eur"] is None


def test_conflicting_reviewed_series_does_not_pick_arbitrary_identity(data):
    db, client = data
    a = offer(db)
    b = offer(db, day=2)
    link(db, a, product(db))
    link(db, b, product(db))
    body = get(client, b)
    assert body["comparison_status"] == "identity_conflict"
    assert body["canonical_product_id"] is None
    assert len(body["observations"]) == 2


def test_bounded_history_and_invalid_input(data):
    db, client = data
    offer(db)
    row = offer(db, day=2)
    body = get(client, row, limit=1)
    assert body["history_truncated"] is True
    assert len(body["observations"]) == 1
    assert client.get(f"/api/v1/offers/{row.id}/price-intelligence?limit=501").status_code == 422
    assert client.get(f"/api/v1/offers/{uuid4()}/price-intelligence").status_code == 404


def test_history_as_of_uses_berlin_day_and_excludes_future_observations(data):
    db, client = data
    old = offer(db, day=1)
    future = offer(db, day=2)
    future.collected_at = datetime(2026, 9, 1, 22, 0, tzinfo=timezone.utc)
    db.flush()
    body = get(client, old, as_of="2026-09-01")
    assert [item["offer_candidate_id"] for item in body["observations"]] == [str(old.id)]
    assert get(client, old, as_of="2026-08-31")["history_scope"] == "no_observations"


def test_comparison_as_of_does_not_replace_known_price_with_future_observation(data):
    db, client = data
    old = offer(db, day=1, price="2.19")
    other = offer(db, day=1, chain="netto", price="2.09")
    canonical = product(db)
    link(db, old, canonical)
    link(db, other, canonical)
    offer(db, day=3, price="0.01")
    body = get(client, old, as_of="2026-09-02")
    assert body["lowest_price_eur"] == "2.09"
    assert {row["price_eur"] for row in body["offers"]} == {"2.19", "2.09"}
    assert client.get(f"/api/v1/offers/{old.id}/price-intelligence?as_of=9999-12-31").status_code == 422
