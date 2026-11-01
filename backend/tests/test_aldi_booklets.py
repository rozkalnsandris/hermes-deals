"""ALDI catalogue link must not claim publication/date/page identity."""
from datetime import date

import pytest

from app.aldi_booklets import OFFICIAL_CATALOGUE, build_aldi_nord_booklet


@pytest.mark.parametrize("day", [
    date(2026, 10, 26), date(2026, 10, 31), date(2026, 11, 1),
    date(2026, 11, 2), date(2026, 11, 7), date(2026, 11, 8),
])
def test_current_and_next_week_only_get_undated_catalogue(day):
    result = build_aldi_nord_booklet(day, today=date(2026, 10, 31))
    assert result["state"] == "external_link"
    assert result["source_url"] == OFFICIAL_CATALOGUE
    assert result["link_label"] == "Atvērt ALDI Nord bukletu katalogu"
    assert result["offers"] == []
    for key in ("image_url", "page_count", "pages", "valid_from", "valid_until"):
        assert key not in result


@pytest.mark.parametrize("day", [date(2026, 10, 25), date(2026, 11, 9)])
def test_out_of_window_dates_do_not_get_live_catalogue_link(day):
    result = build_aldi_nord_booklet(day, today=date(2026, 10, 31))
    assert result["state"] == "unavailable"
    assert result["offers"] == []
    assert "source_url" not in result


def test_sunday_publication_rollover_does_not_guess_current_or_preview():
    # On 2026-11-01 ALDI already labelled the Nov 2 edition "aktuell"
    # and the Nov 9 edition "vorschau", before the local week changed.
    old = build_aldi_nord_booklet(date(2026, 11, 1), today=date(2026, 11, 1))
    next_week = build_aldi_nord_booklet(date(2026, 11, 2), today=date(2026, 11, 1))
    assert old["source_url"] == next_week["source_url"] == OFFICIAL_CATALOGUE
    for result in (old, next_week):
        assert result["state"] == "external_link"
        assert "valid_label" not in result
        assert "pages" not in result
