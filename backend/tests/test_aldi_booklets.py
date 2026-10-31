"""ALDI booklet links have bounded calendar scope and no fabricated pages."""
from datetime import date

import pytest

from app.aldi_booklets import (
    OFFICIAL_CURRENT, OFFICIAL_PREVIEW, build_aldi_nord_booklet,
)


@pytest.mark.parametrize(("day", "expected_url"), [
    (date(2026, 10, 26), OFFICIAL_CURRENT),
    (date(2026, 10, 31), OFFICIAL_CURRENT),
    (date(2026, 11, 1), OFFICIAL_CURRENT),
    (date(2026, 11, 2), OFFICIAL_PREVIEW),
    (date(2026, 11, 7), OFFICIAL_PREVIEW),
    (date(2026, 11, 8), OFFICIAL_PREVIEW),
])
def test_current_and_next_official_link_only(day, expected_url):
    result = build_aldi_nord_booklet(day, today=date(2026, 10, 31))
    assert result["state"] == "external_link"
    assert result["source_url"] == expected_url
    assert result["offers"] == []
    assert "image_url" not in result
    assert "page_count" not in result
    assert "pages" not in result


@pytest.mark.parametrize("day", [date(2026, 10, 25), date(2026, 11, 9)])
def test_other_weeks_never_link_to_the_wrong_brochure(day):
    result = build_aldi_nord_booklet(day, today=date(2026, 10, 31))
    assert result["state"] == "unavailable"
    assert result["offers"] == []
    assert "source_url" not in result


def test_sunday_rollover_is_berlin_calendar_week():
    result = build_aldi_nord_booklet(date(2026, 11, 2), today=date(2026, 11, 1))
    assert result["state"] == "external_link"
    assert result["source_url"] == OFFICIAL_PREVIEW
