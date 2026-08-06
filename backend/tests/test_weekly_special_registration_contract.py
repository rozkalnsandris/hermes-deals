from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
APP = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")


def test_weekly_special_endpoint_and_single_request_ui_are_registered_once() -> None:
    assert MAIN.count(
        "from app.weekly_special_api import router as weekly_special_router"
    ) == 1
    assert MAIN.count("app.include_router(weekly_special_router)") == 1
    assert APP.count("/api/v1/deals/weekly-specials?") == 1
    assert "async function weeklyFetchWeek(start)" in APP
    assert "async function weeklyFetchDay(iso)" not in APP
    assert "Promise.all(remaining.map(iso=>weeklyLoadDate(iso,token)))" not in APP
