"""Same discovery contract on SQLite and the migrated PostgreSQL CI service."""
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db import engine as configured_engine
from app.models import Base, OfferCandidateRecord, SourceSnapshot
from app.price_intelligence import _series_predicate, list_price_history_series

DAY = date(2026, 10, 27)


@pytest.fixture(params=["sqlite", "postgresql"])
def history_db(request):
    if request.param == "postgresql":
        if configured_engine.dialect.name != "postgresql":
            pytest.skip("requires migrated PostgreSQL CI service")
        engine = configured_engine
    else:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
    with Session(engine) as db:
        def add(**overrides):
            snapshot = SourceSnapshot(source_chain="lidl", source_url="https://example.invalid/history-test",
                                      collected_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                                      strategy_hint="test", success=True)
            db.add(snapshot)
            db.flush()
            values = dict(snapshot_id=snapshot.id, source_chain="lidl", source_store_external_id="one",
                          source_offer_id="milk", product_name_raw="HistoryTest Milk", brand_raw="Test",
                          package_text_raw="1 l", unit_label="l", price_eur=Decimal("1.29"),
                          collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
                          valid_from=date(2026, 9, 28), valid_until=date(2026, 10, 4),
                          source_url="https://example.invalid/history-test", parser_version="test")
            values.update(overrides)
            row = OfferCandidateRecord(**values)
            db.add(row)
            db.flush()
            return row
        yield db, add
        db.rollback()
    if request.param == "sqlite":
        engine.dispose()


def discover(db, **kwargs):
    return list_price_history_series(db, as_of=kwargs.pop("as_of", DAY),
                                     query=kwargs.pop("query", "HistoryTest"), **kwargs)


def test_latest_expired_observation_and_fixed_mode_equivalence(history_db):
    db, add = history_db
    old = add(pricing_mode=None)
    latest = add(pricing_mode="fixed_package", collected_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    rows, count = discover(db)
    assert count == 1
    assert [row.id for row in rows] == [latest.id]
    assert {row.id for row in db.scalars(select(OfferCandidateRecord).where(_series_predicate(latest)))} == {old.id, latest.id}


@pytest.mark.parametrize("change", [
    {"source_chain": "netto"}, {"source_store_external_id": "two"}, {"source_store_external_id": None},
    {"source_offer_id": "other"}, {"product_name_raw": "HistoryTest Other"}, {"brand_raw": "Other"},
    {"brand_raw": None}, {"package_text_raw": "2 l"}, {"unit_label": "kg"},
    {"requires_app": True}, {"coupon_required": True}, {"pricing_mode": "unit_price_only"},
])
def test_identity_boundaries_match_detail_service(history_db, change):
    db, add = history_db
    first, second = add(), add(**change)
    rows, count = discover(db)
    assert count == 2
    assert {row.id for row in rows} == {first.id, second.id}
    for row in rows:
        assert list(db.scalars(select(OfferCandidateRecord.id).where(_series_predicate(row)))) == [row.id]


@pytest.mark.parametrize("unknown", [
    {"source_offer_id": None}, {"source_offer_id": ""}, {"package_text_raw": None},
    {"package_text_raw": ""}, {"package_text_raw": "\t\n\u00a0\u3000"},
    {"pricing_mode": "unknown"}, {"pricing_mode": "unit_price_only", "unit_label": None},
])
def test_unknown_identity_or_basis_never_merges_observations(history_db, unknown):
    db, add = history_db
    add(**unknown)
    add(**unknown)
    rows, count = discover(db)
    assert count == len(rows) == 2


@pytest.mark.parametrize("day,utc_hour", [(date(2026, 10, 24), 22), (date(2026, 10, 25), 23)])
def test_berlin_cutoff_across_dst_and_no_future_leak(history_db, day, utc_hour):
    db, add = history_db
    latest = add(collected_at=datetime(2026, 10, day.day, utc_hour - 1, 59, 59, tzinfo=timezone.utc))
    add(collected_at=datetime(2026, 10, day.day, utc_hour, tzinfo=timezone.utc))
    add(source_offer_id="future-only", collected_at=datetime(2026, 10, 28, tzinfo=timezone.utc))
    rows, count = discover(db, as_of=day)
    assert count == 1
    assert [row.id for row in rows] == [latest.id]


def test_timestamp_tie_is_deterministic(history_db):
    db, add = history_db
    add(id=UUID(int=101))
    winner = add(id=UUID(int=100))
    assert [row.id for row in discover(db)[0]] == [winner.id]


def test_literal_search_brand_sku_and_retailer_filter(history_db):
    db, add = history_db
    literal = add(product_name_raw="HistoryTest 10%_milk")
    add(product_name_raw="HistoryTest 100Xmilk", source_offer_id="different")
    add(source_chain="netto", product_name_raw="HistoryTest 10%_milk")
    for query in ("historytest 10%_", "Test", "milk"):
        rows, _ = discover(db, query=query, retailer="lidl")
        assert literal.id in {row.id for row in rows}
    assert [row.id for row in discover(db, query="HistoryTest 10%_", retailer="lidl")[0]] == [literal.id]
    assert discover(db, query="HistoryTest nonexistent") == ([], 0)


def test_pagination_counts_series_and_only_hydrates_page(history_db):
    db, add = history_db
    for i in range(65):
        for day in range(1, 4):
            add(source_offer_id=f"milk-{i:03}", product_name_raw=f"HistoryTest Milk {i:03}",
                collected_at=datetime(2026, 10, day, tzinfo=timezone.utc))
    db.expunge_all()
    loaded = []
    def on_load(session, row):
        if isinstance(row, OfferCandidateRecord):
            loaded.append(row.id)
    event.listen(db, "loaded_as_persistent", on_load)
    rows, count = discover(db, offset=60, limit=60)
    assert count == 65
    assert [row.source_offer_id for row in rows] == [f"milk-{i:03}" for i in range(60, 65)]
    assert len(loaded) == 5
    assert all(row.collected_at.day == 3 for row in rows)
    assert discover(db, offset=120) == ([], 65)
    event.remove(db, "loaded_as_persistent", on_load)


@pytest.mark.parametrize("sort,expected", [("name", ["A", "B"]), ("retailer", ["B", "A"]), ("newest", ["B", "A"])])
def test_sorting(history_db, sort, expected):
    db, add = history_db
    add(source_offer_id="A", product_name_raw="HistoryTest A", source_chain="netto")
    add(source_offer_id="B", product_name_raw="HistoryTest B", source_chain="lidl",
        collected_at=datetime(2026, 10, 2, tzinfo=timezone.utc))
    assert [row.source_offer_id for row in discover(db, sort=sort)[0]] == expected
