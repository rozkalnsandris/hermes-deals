"""ALDI Nord official brochure entry points, not unverified embedded pages."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

OFFICIAL_CURRENT = "https://www.aldi-nord.de/prospekte/aldi-aktuell.html"
OFFICIAL_PREVIEW = "https://www.aldi-nord.de/prospekte/aldi-vorschau.html"


def build_aldi_nord_booklet(day: date, *, today: date | None = None) -> dict:
    current = today if today is not None else datetime.now(ZoneInfo("Europe/Berlin")).date()
    monday = current - timedelta(days=current.weekday())
    current_end = monday + timedelta(days=6)
    preview_end = monday + timedelta(days=13)
    empty = {
        "state": "unavailable",
        "offers": [],
        "message": "Šim datumam nav reģistrētas pārbaudītas ALDI Nord bukleta lapas.",
    }
    if monday <= day <= current_end:
        source_url = OFFICIAL_CURRENT
    elif current_end < day <= preview_end:
        source_url = OFFICIAL_PREVIEW
    else:
        return empty
    return {
        "state": "external_link",
        "offers": [],
        "source_url": source_url,
        "message": (
            "Atvērt ALDI Nord oficiālo bukletu veikala vietnē. "
            "Hermes Deals vēl nav verificējis šī izdevuma lapas un produktu sasaisti."
        ),
    }
