from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "ui"
INDEX = (UI / "index.html").read_text(encoding="utf-8")
STYLES = (UI / "styles.css").read_text(encoding="utf-8")
APP = (UI / "app.js").read_text(encoding="utf-8")
REVIEW = (UI / "review.html").read_text(encoding="utf-8")


def test_every_weekly_visible_date_uses_full_latvian_format() -> None:
    assert 'function fmtDate(v)' in APP
    assert 'function weeklyShortDate(iso)' in APP
    assert '.${date.getFullYear()}`;}' in APP
    assert 'return `${weeklyShortDate(dates[0])}–${weeklyShortDate(dates[6])}`;' in APP
    assert 'return `${String(date.getDate()).padStart(2,"0")}.${String(date.getMonth()+1).padStart(2,"0")}.`;}' not in APP


def test_as_of_date_is_berlin_based_and_url_input_is_validated() -> None:
    assert 'timeZone:"Europe/Berlin"' in APP
    assert 'function isIsoDate(v)' in APP
    assert 'function setAsOfIso(v){const iso=isIsoDate(v)?String(v):todayLocal();' in APP
    assert 'if(p.has("date"))setAsOfIso(p.get("date"));' in APP
    assert 'function weeklyBerlinToday(){return todayLocal();}' in APP


def test_primary_family_workflows_clip_page_overflow_without_hiding_inner_scrollers() -> None:
    assert 'html,body{max-width:100%;overflow-x:hidden;overflow-x:clip}' in STYLES
    assert '.weekly-app-actions{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);width:100%;min-width:0}' in STYLES
    assert '.filter-summary .reset-filters{width:100%;margin-left:0}' in STYLES
    assert '.weekly-main-nav::-webkit-scrollbar{display:none}' in STYLES
    assert '.weekly-main-nav' in STYLES and 'overflow-x:auto' in STYLES


def test_calendar_controls_remain_button_anchored_and_touch_sized() -> None:
    assert 'id="asOfPickerButton"' in INDEX
    assert 'id="weeklyDateButton"' in INDEX
    assert '.weekly-date-control{\n      position:relative;' in STYLES
    assert '.weekly-date-input{\n      position:absolute;\n      inset:0;' in STYLES
    assert '@media(pointer:coarse)' in STYLES
    assert 'min-height:44px' in STYLES


def test_review_mobile_sticky_actions_respect_safe_areas() -> None:
    assert 'content="width=device-width,initial-scale=1,viewport-fit=cover"' in REVIEW
    assert 'html,body{max-width:100%;overflow-x:hidden;overflow-x:clip}' in REVIEW
    assert '.actions.sticky-actions{padding-bottom:max(12px,env(safe-area-inset-bottom))}' in REVIEW
    assert '.toolbar>*{flex:1 1 100%;width:100%}' in REVIEW
    assert 'placeholder="DD.MM.GGGG"' in REVIEW


def test_normal_family_body_has_no_preview_or_diagnostic_copy() -> None:
    visible = re.sub(r'<!--.*?-->', '', INDEX, flags=re.S)
    body = visible.split('<body', 1)[1]
    assert 'preview-only' not in body.lower()
    assert 'diagnostic' not in body.lower()


def test_filters_remain_visible_and_reversible() -> None:
    assert 'id="filterSummary"' in INDEX
    assert 'function renderFilterSummary()' in APP
    assert 'function resetFilters()' in APP
    assert 'id="activeFilterCount"' in INDEX
