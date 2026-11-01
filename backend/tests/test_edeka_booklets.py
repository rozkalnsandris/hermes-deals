"""EDEKA Patzer booklet entry is market-bound and fail-closed on dates."""
from datetime import date, datetime

import pytest

from app.edeka_booklets import (
    build_edeka_booklet, MARKET_CODE, MARKET_NAME, OFFICIAL_PROSPECTS,
)


def test_official_catalogue_is_same_market_as_collector():
    from app.edeka_store_offers import _EXPECTED_PUBLIC_MARKET_ID, _EXPECTED_SCOPE
    assert MARKET_CODE == _EXPECTED_PUBLIC_MARKET_ID == "071897"
    assert _EXPECTED_SCOPE == "family_primary_edeka"
    assert OFFICIAL_PROSPECTS == "https://www.edeka.de/maerkte/071897/prospekte/"
    assert "Dortmund-Wickede" in MARKET_NAME


@pytest.mark.parametrize("selected", [
    date(2026, 10, 26), date(2026, 11, 1),
    date(2026, 11, 2), date(2026, 11, 8),
])
def test_current_or_next_berlin_week_links_only_to_official_market_catalogue(selected):
    record = build_edeka_booklet(selected, today=date(2026, 11, 1))
    assert record["state"] == "external_link"
    assert record["source_url"] == OFFICIAL_PROSPECTS
    assert record["store_name"] == MARKET_NAME
    assert "var neatbilst" in record["message"]
    assert record["offers"] == []
    for forbidden in ("pages", "page_count", "image_url", "snapshot_id", "valid_label"):
        assert forbidden not in record


@pytest.mark.parametrize("selected", [
    date(2026, 10, 25), date(2026, 11, 9), date(2026, 1, 1),
])
def test_historical_or_far_future_date_does_not_reuse_dynamic_link(selected):
    record = build_edeka_booklet(selected, today=date(2026, 11, 1))
    assert record["state"] == "unavailable"
    assert "source_url" not in record
    assert "image_url" not in record
    assert record["offers"] == []


@pytest.mark.parametrize("invalid", [None, "2026-11-02", datetime(2026, 11, 2)])
def test_invalid_day_type_never_publishes(invalid):
    with pytest.raises(ValueError):
        build_edeka_booklet(invalid, today=date(2026, 11, 1))
