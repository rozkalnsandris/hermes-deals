"""The official market-bound EDEKA Patzer original-booklet entry point.

Unlike Netto's Publitas or ALDI's independently verified iPaper issue,
the current EDEKA Patzer source exposes a market-scoped brochure *dialog*.
No immutable issue/page image manifest has been captured. A safe external
link is not evidence that the selected calendar date has a matching edition.
No product mapping, source harvesting or local PDF storage occurs here.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# The existing canonical collector / identity gates bind the family to Patzer.
MARKET_CODE = "071897"
MARKET_NAME = "EDEKA Patzer · Eichwaldstraße 5–7, Dortmund-Wickede"
OFFICIAL_PROSPECTS = "https://www.edeka.de/maerkte/071897/prospekte/"


def build_edeka_booklet(day: date, *, today: date | None = None) -> dict:
    """Link only to the immutable *market identity*, not an assumed edition."""
    if type(day) is not date:
        raise ValueError("Invalid EDEKA booklet date")
    current = today if today is not None else datetime.now(ZoneInfo("Europe/Berlin")).date()
    if type(current) is not date:
        raise ValueError("Invalid EDEKA reference date")
    monday = current - timedelta(days=current.weekday())
    # Live EDEKA landing can rotate before the weekly boundary; do not link
    # unrelated historical/far-future selections to today's dynamic catalogue.
    if not monday <= day <= monday + timedelta(days=13):
        return {
            "state": "unavailable", "offers": [],
            "store_name": MARKET_NAME,
            "message": "Šim datumam nav reģistrētas pārbaudītas EDEKA Patzer bukleta lapas.",
        }
    return {
        "state": "external_link", "offers": [],
        "store_name": MARKET_NAME,
        "source_url": OFFICIAL_PROSPECTS,
        "link_label": "Atvērt EDEKA Patzer bukletu katalogu",
        "message": (
            "EDEKA Patzer oficiālajā vietnē atver 'Angebote der Woche' bukletu. "
            "Lapa rāda veikala aktuālos izdevumus, kas var neatbilst izvēlētajam "
            "Hermes Deals datumam. Bukleta lapas un produktu saites vēl nav "
            "neatkarīgi verificētas."
        ),
    }
