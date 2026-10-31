"""Booklet navigation must not run unrelated household projections."""

from datetime import date

import pytest

from app import north_star_live_data as live_data


@pytest.mark.parametrize("retailer", ["netto", "lidl"])
def test_booklet_navigation_skips_catalogue_basket_and_meal_projections(monkeypatch, retailer):
    day = date(2026, 11, 2)
    state = {
        "settings": {"household": "Testa ģimene", "location": "Dortmunde"},
        "shopping": [{"item_id": "existing"}],
        "favorites": [],
        "price_eligibility": {},
    }
    monkeypatch.setattr(live_data, "read_household", lambda db, household: (state, 7))
    read_page = []

    def booklet_reader(db, selected_day, page):
        read_page.append((selected_day, page))
        return {"state": "unavailable", "offers": [], "message": "Testa buklets nav pieejams."}

    monkeypatch.setattr(live_data, f"build_{retailer}_booklet", booklet_reader)

    def unexpected(*args, **kwargs):
        raise AssertionError("Unrelated database/domain projection ran during booklet navigation")

    for name in (
        "build_current_deals",
        "build_current_deals_status",
        "load_sql_ranked_state_rows",
        "list_price_history_series",
        "build_offer_price_intelligence",
        "meal_context",
        "best_two_store_plan",
    ):
        monkeypatch.setattr(live_data, name, unexpected)

    context = live_data.build_live_context(
        object(), "test-family", day, view="booklets",
        booklet_retailer=retailer, booklet_page=3,
    )

    assert read_page == [(day, 3)]
    assert context["booklet"]["retailer_id"] == retailer
    assert context["booklet"]["state"] == "unavailable"
    assert context["state_version"] == 7
    assert context["shopping"]["count"] == 1
    assert context["settings"] == state["settings"]
    assert context["selected_date"] == "2026-11-02"
    assert context["selected_product"] is None
    assert context["read_error"] is False


def test_booklet_navigation_does_not_invent_other_retailer_pages(monkeypatch):
    state = {
        "settings": {"household": "Testa ģimene", "location": "Dortmunde"},
        "shopping": [], "favorites": [], "price_eligibility": {},
    }
    monkeypatch.setattr(live_data, "read_household", lambda db, household: (state, 0))

    def unexpected(*args, **kwargs):
        raise AssertionError("Unverified retailer must not use a page reader")

    monkeypatch.setattr(live_data, "build_netto_booklet", unexpected)
    monkeypatch.setattr(live_data, "build_lidl_booklet", unexpected)

    context = live_data.build_live_context(
        object(), "test-family", date(2026, 11, 2),
        view="booklets", booklet_retailer="aldi_nord",
    )

    assert context["booklet"]["state"] == "unavailable"
    assert context["booklet"]["offers"] == []
    assert context["booklet"]["retailer_name"] == "ALDI Nord"
