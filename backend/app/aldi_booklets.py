"""ALDI Nord official catalogue, never an inferred publication.

Current/preview aliases can rotate before the Berlin ISO-week boundary.
Without a source-bound issue/date/page manifest, a catalogue is the only
honest official entry point.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

OFFICIAL_CATALOGUE = "https://www.aldi-nord.de/prospekte.html"


def build_aldi_nord_booklet(day: date, *, today: date | None = None) -> dict:
    current = today if today is not None else datetime.now(ZoneInfo("Europe/Berlin")).date()
    monday = current - timedelta(days=current.weekday())
    if not monday <= day <= monday + timedelta(days=13):
        return {
            "state": "unavailable",
            "offers": [],
            "message": "Šim datumam nav reģistrētas pārbaudītas ALDI Nord bukleta lapas.",
        }
    return {
        "state": "external_link",
        "offers": [],
        "source_url": OFFICIAL_CATALOGUE,
        "link_label": "Atvērt ALDI Nord bukletu katalogu",
        "message": (
            "ALDI Nord oficiālajā katalogā izvēlies izdevumu pēc tā datuma. "
            "Hermes Deals vēl nav verificējis atlasītā datuma bukletu, "
            "lapas vai produktu sasaisti."
        ),
    }
