from datetime import date
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_weekly_live_source import (  # noqa: E402
    WeeklyLiveSourceError,
    select_latest_nonexpired,
)
from app.netto_store_prospect import NettoStoreProspectBundle  # noqa: E402
from netto_weekly_transition_state import SELECTOR_STRATEGY  # noqa: E402


def _bundle(slug: str, start: date, end: date) -> NettoStoreProspectBundle:
    return NettoStoreProspectBundle(
        store_url="https://www.netto-online.de/filialen/dortmund/hallesche-str-80/5659",
        prospect_url=f"https://wochenprospekt.netto-online.de/{slug}",
        prospect_slug=slug,
        store_html=b"<html></html>",
        prospect_html=b"<html></html>",
        valid_from=start,
        valid_until=end,
        validity_text=f"{start.isoformat()} - {end.isoformat()}",
        selected_store_cookie_present=True,
        elapsed_ms=0,
        publication_json=b"{}",
        prospect_pdf_url=f"https://example.invalid/{slug}.pdf",
        prospect_pdf=b"%PDF-test",
    )


def test_weekly_source_selects_latest_nonexpired_future_window() -> None:
    current = _bundle("hz36", date(2026, 8, 31), date(2026, 9, 5))
    preview = _bundle("hz37", date(2026, 9, 7), date(2026, 9, 12))

    selected = select_latest_nonexpired([current, preview], as_of=date(2026, 9, 6))

    assert selected.prospect_slug == "hz37"


def test_weekly_source_fails_closed_when_latest_window_is_ambiguous() -> None:
    first = _bundle("hz37-a", date(2026, 9, 7), date(2026, 9, 12))
    second = _bundle("hz37-b", date(2026, 9, 7), date(2026, 9, 12))

    try:
        select_latest_nonexpired([first, second], as_of=date(2026, 9, 6))
    except WeeklyLiveSourceError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous latest weekly window must fail closed")


def test_weekly_contract_is_not_heldout_identity_bound() -> None:
    live_text = (TOOLS / "netto_weekly_live_source.py").read_text(encoding="utf-8")
    selector_text = (TOOLS / "netto_weekly_source_selector.py").read_text(encoding="utf-8")

    assert "EXPECTED_CAPTURE_IDENTITY" not in live_text
    assert "owner-frozen #831" not in live_text
    assert "EXISTING_EVALUATION_CAMPAIGNS" not in selector_text
    assert "netto_weekly_verified_source_selector_v1" == SELECTOR_STRATEGY
