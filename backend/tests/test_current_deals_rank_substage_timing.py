from __future__ import annotations

from app.current_deals_route_installer import _server_timing_header
from app.current_deals_sql_loader import capture_rank_substage_timings


def test_server_timing_adds_rank_substages_after_rank_metric() -> None:
    header = _server_timing_header(
        250.0,
        {
            "cache": 0.01,
            "cache_state": "miss",
            "rank": 220.0,
            "filter-sort": 5.0,
            "canonical": 20.0,
            "model": 0.5,
        },
        {
            "winner": 180.0,
            "rescue": 2.0,
            "materialize": 37.0,
        },
    )

    assert "current-deals-rank;dur=220.0" in header
    assert "current-deals-winner;dur=180.0" in header
    assert "current-deals-rescue;dur=2.0" in header
    assert "current-deals-materialize;dur=37.0" in header
    assert header.index("current-deals-rank") < header.index("current-deals-winner")
    assert header.index("current-deals-winner") < header.index("current-deals-rescue")
    assert header.index("current-deals-rescue") < header.index("current-deals-materialize")
    assert header.index("current-deals-materialize") < header.index("current-deals-filter")


def test_cache_hit_header_does_not_invent_rank_substages() -> None:
    header = _server_timing_header(
        0.04,
        {"cache": 0.01, "cache_state": "hit"},
        {},
    )

    assert header == (
        "current-deals-sql;dur=0.0, "
        "current-deals-cache;dur=0.0;desc=hit"
    )


def test_rank_substage_timing_context_is_nested_and_restored() -> None:
    with capture_rank_substage_timings() as outer:
        outer["winner"] = 11.0
        with capture_rank_substage_timings() as inner:
            inner["winner"] = 22.0
        assert outer == {"winner": 11.0}
        assert inner == {"winner": 22.0}

    with capture_rank_substage_timings() as fresh:
        assert fresh == {}
