"""HTML/API current-deals cache sharing and household separation contracts."""

from datetime import date, datetime, timezone
from decimal import Decimal
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import current_deals_fast_route as fast_cache
from app import current_deals_route_installer as route_installer
from app import north_star_live_data as live_data
from app.db import get_db
from app.main import app
from app.models import Base, OfferCandidateRecord, SourceSnapshot

DAY = date(2026, 10, 1)


@pytest.fixture
def ui_and_db(monkeypatch):
    monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", "1")
    monkeypatch.setenv("HERMES_HOUSEHOLD_ID", "test-family")
    monkeypatch.delenv("HERMES_PUBLIC_ORIGIN", raising=False)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def get_test_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    fast_cache._clear_current_deals_cache()
    try:
        with Session(engine, expire_on_commit=False) as db, TestClient(app) as client:
            snapshot = SourceSnapshot(
                source_chain="lidl", source_url="https://example.invalid/flyer",
                collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
                strategy_hint="test", success=True,
            )
            db.add(snapshot)
            db.flush()
            row = OfferCandidateRecord(
                snapshot_id=snapshot.id, source_chain="lidl",
                source_store_external_id="store-one", source_offer_id="milk",
                product_name_raw="Piens", price_eur=Decimal("1.29"),
                package_text_raw="1 l", brand_raw="Test",
                unit_label="l", unit_price_eur=Decimal("1.29"),
                valid_from=date(2026, 9, 28), valid_until=date(2026, 10, 4),
                collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
                source_url="https://example.invalid/flyer", parser_version="test",
            )
            db.add(row)
            db.commit()
            yield db, client, row
    finally:
        fast_cache._clear_current_deals_cache()
        app.dependency_overrides.clear()
        engine.dispose()


def test_sqlite_household_ui_bypasses_shared_production_cache(ui_and_db, monkeypatch):
    db, client, row = ui_and_db
    assert live_data._postgres_public_cache(db) is False

    def unexpected(*args, **kwargs):
        raise AssertionError("SQLite test database may not read the process-wide offer cache")

    monkeypatch.setattr(fast_cache, "cached_current_deals", unexpected)
    response = client.get("/ui/home/?view=deals&date=2026-10-01")
    assert response.status_code == 200
    assert "Piens" in response.text


def test_api_and_html_share_public_key_but_refresh_household_state(ui_and_db, monkeypatch):
    db, client, row = ui_and_db
    # Emulate the production PostgreSQL cache boundary on an isolated test DB.
    # Both routes must independently enforce the same non-SQLite cache policy.
    monkeypatch.setattr(live_data, "_postgres_public_cache", lambda db: True)
    monkeypatch.setattr(route_installer, "_is_postgresql", lambda db: True)

    with patch.object(fast_cache, "build_current_deals", wraps=fast_cache.build_current_deals) as build:
        api = client.get("/api/v1/deals/current?as_of=2026-10-01&limit=60")
        assert api.status_code == 200, api.text
        assert api.json()["deals"][0]["offer_candidate_id"] == str(row.id)
        first = live_data.build_live_context(db, "test-family", DAY, view="deals")
        assert first["offers"][0]["id"] == str(row.id)
        assert first["offers"][0]["favorite"] is False
        assert build.call_count == 1  # the API warmed the exact shared key

        initial = client.get("/ui/home/?view=deals&date=2026-10-01")
        assert initial.status_code == 200
        token = re.search(r'name="csrf_token" value="([^"]+)"', initial.text)[1]
        version = re.search(r'name="version" value="([^"]+)"', initial.text)[1]
        saved = client.post(
            "/ui/home/actions/favorite",
            data={
                "csrf_token": token, "version": version,
                "date": "2026-10-01", "return_view": "deals",
                "product_id": str(row.id),
            },
            headers={"Origin": "http://testserver"},
            follow_redirects=False,
        )
        assert saved.status_code == 303
        household = live_data.build_live_context(db, "test-family", DAY, view="deals")
        other = live_data.build_live_context(db, "another-family", DAY, view="deals")
        assert household["offers"][0]["favorite"] is True
        assert household["favorites"][0]["id"] == str(row.id)
        assert other["offers"][0]["favorite"] is False
        assert other["favorites"] == []
        assert build.call_count == 1  # personalized fields never entered the public cache

        filtered = live_data.build_live_context(db, "test-family", DAY, view="deals", retailer="lidl")
        assert filtered["offers"][0]["id"] == str(row.id)
        assert build.call_count == 2  # retailer changes the public cache key


def test_html_cache_expires_and_new_date_has_independent_key(ui_and_db, monkeypatch):
    db, _, row = ui_and_db
    monkeypatch.setattr(live_data, "_postgres_public_cache", lambda db: True)
    monkeypatch.setattr(fast_cache, "_CACHE_TTL_SECONDS", 60.0)
    clock = [1000.0]
    monkeypatch.setattr(fast_cache, "monotonic", lambda: clock[0])

    with patch.object(fast_cache, "build_current_deals", wraps=fast_cache.build_current_deals) as build:
        first = live_data.build_live_context(db, "test-family", DAY, view="overview")
        repeated = live_data.build_live_context(db, "test-family", DAY, view="deals")
        assert build.call_count == 1
        assert repeated["offers"] == first["offers"]

        clock[0] += 61
        refreshed = live_data.build_live_context(db, "test-family", DAY, view="deals")
        assert build.call_count == 2
        assert refreshed["offers"] == first["offers"]

        live_data.build_live_context(db, "test-family", date(2026, 10, 2), view="deals")
        assert build.call_count == 3
