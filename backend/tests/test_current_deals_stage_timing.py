from __future__ import annotations

from datetime import date
from time import perf_counter

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import current_deals_fast_route as fast_route
from app.current_deals_route_installer import _server_timing_header
from app.models import Base


def _empty_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _call_empty_current(session: Session):
    return fast_route.fast_current_deals(
        as_of=date(2026, 8, 7),
        q=None,
        retailer=None,
        view="current",
        app_only=False,
        coupon_only=False,
        discount_only=False,
        image_only=False,
        sort="name",
        offset=0,
        limit=12,
        db=session,
    )


def test_server_timing_preserves_total_and_adds_short_stage_metrics() -> None:
    header = _server_timing_header(
        432.15,
        {
            "cache": 0.08,
            "cache_state": "miss",
            "rank": 250.44,
            "filter-sort": 4.25,
            "canonical": 170.91,
            "model": 1.06,
        },
    )

    assert header == (
        "current-deals-sql;dur=432.1, "
        "current-deals-cache;dur=0.1;desc=miss, "
        "current-deals-rank;dur=250.4, "
        "current-deals-filter;dur=4.2, "
        "current-deals-canonical;dur=170.9, "
        "current-deals-model;dur=1.1"
    )


def test_request_local_timing_context_is_isolated_and_restored() -> None:
    with fast_route.capture_current_deals_timings() as outer:
        fast_route._record_cache_state("miss")
        fast_route._record_stage("cache", perf_counter())

        with fast_route.capture_current_deals_timings() as inner:
            fast_route._record_cache_state("hit")
            fast_route._record_stage("cache", perf_counter())

        assert outer["cache_state"] == "miss"
        assert inner["cache_state"] == "hit"
        assert isinstance(outer["cache"], float)
        assert isinstance(inner["cache"], float)

    with fast_route.capture_current_deals_timings() as fresh:
        assert fresh == {}


def test_fast_route_distinguishes_cache_miss_and_hit() -> None:
    session = _empty_session()
    fast_route._clear_current_deals_cache()

    with fast_route.capture_current_deals_timings() as miss_timings:
        first = _call_empty_current(session)

    with fast_route.capture_current_deals_timings() as hit_timings:
        second = _call_empty_current(session)

    assert first == second
    assert miss_timings["cache_state"] == "miss"
    assert "rank" in miss_timings
    assert "filter-sort" in miss_timings
    assert "canonical" in miss_timings
    assert "model" in miss_timings

    assert hit_timings["cache_state"] == "hit"
    assert "cache" in hit_timings
    assert "rank" not in hit_timings
    assert "canonical" not in hit_timings
