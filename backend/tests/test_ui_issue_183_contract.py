from __future__ import annotations

from pathlib import Path


APP = (
    Path(__file__).resolve().parents[1] / "app" / "ui" / "app.js"
).read_text(encoding="utf-8")


def test_quick_date_offsets_use_the_authoritative_berlin_calendar_chain() -> None:
    assert 'timeZone:"Europe/Berlin"' in APP
    assert 'function addDaysIso(iso,days)' in APP
    assert (
        'function dateFromOffset(offset){return '
        'addDaysIso(todayLocal(),Number(offset));}'
    ) in APP
    assert 'function dateFromOffset(offset){const d=new Date();' not in APP
    assert 'setAsOfIso(dateFromOffset(b.dataset.offset));' in APP
