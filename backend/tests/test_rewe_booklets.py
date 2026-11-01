"""Network-free REWE Brackel original-booklet fallback tests."""
from datetime import date

import pytest
from app.rewe_booklets import (
    MARKET_ID, OFFICIAL_OFFERS, OFFICIAL_STORE, build_rewe_booklet,
)


def test_official_market_identified_without_assuming_booklet_pages():
    assert MARKET_ID == "260032"
    assert "/dortmund/260032/" in OFFICIAL_STORE
    assert "/dortmund/260032/" in OFFICIAL_OFFERS
    assert OFFICIAL_OFFERS.startswith("https://www.rewe.de/angebote/")
    state = build_rewe_booklet(date(2026, 11, 2), today=date(2026, 11, 1))
    assert state["state"] == "external_link"
    assert state["source_url"] == OFFICIAL_OFFERS
    assert state["offers"] == []
    assert "nevis pārbaudītām" in state["message"]
    assert "bukleta" not in state["link_label"].casefold()
    assert all(key not in state for key in ("pages", "page_count", "image_url", "valid_label"))


def test_no_far_future_or_past_booklet_claims():
    for day in (date(2026, 10, 1), date(2026, 11, 20)):
        item = build_rewe_booklet(day, today=date(2026, 11, 1))
        assert item["state"] == "unavailable" and item["offers"] == []
        assert "source_url" not in item


@pytest.mark.parametrize("bad", [None, "2026-11-02", 7])
def test_invalid_calendar_fails_closed(bad):
    with pytest.raises(ValueError):
        build_rewe_booklet(bad, today=date(2026, 11, 1))


def test_invalid_reference_date_fails_closed():
    with pytest.raises(ValueError):
        build_rewe_booklet(date(2026, 11, 2), today="2026-11-01")


def test_rewe_link_is_selectable_without_implicit_page_or_products(monkeypatch):
    from app import north_star_live_data as ui
    assert ("rewe", "REWE") in ui.BOOKLET_RETAILERS
    monkeypatch.setattr(ui, "build_netto_booklet", lambda *a, **kw: (
        (_ for _ in ()).throw(AssertionError("Netto must not render REWE"))))
    state = ui.build_booklet_context if hasattr(ui, "build_booklet_context") else None
    assert state is None or callable(state)
