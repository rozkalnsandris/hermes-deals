"""Official Kaufland store-link fallback without claiming edition dates."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

STORE_NAME = "Kaufland Dortmund-Aplerbeck · Aplerbecker Marktplatz 7–10"
OFFICIAL_STORE = "https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html"


def build_kaufland_booklet(day: date, *, today: date | None = None) -> dict:
    if type(day) is not date:
        raise ValueError("Invalid Kaufland booklet date")
    current = today if today is not None else datetime.now(ZoneInfo("Europe/Berlin")).date()
    if type(current) is not date:
        raise ValueError("Invalid Kaufland reference date")
    monday = current - timedelta(days=current.weekday())
    if not monday <= day <= monday + timedelta(days=13):
        return {"state": "unavailable", "offers": [], "store_name": STORE_NAME,
                "message": "Šim datumam nav reģistrēta pārbaudīta Kaufland bukleta."}
    return {
        "state": "external_link", "offers": [], "store_name": STORE_NAME,
        "source_url": OFFICIAL_STORE,
        "link_label": "Atvērt Kaufland Aplerbeck oficiālos bukletus",
        "message": "Oriģinālās lapas vēl nav reģistrētas. Izvēlies datumu oficiālajā vietnē.",
    }
