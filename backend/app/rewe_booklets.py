"""REWE Brackel first-party market link; no unverified brochure pages.

Source-only: REWE's official store #260032 pages currently expose offer cards,
but their brochure widget reports a technical problem (2026-11-01).
Never substitute aggregator PDFs, another store's issue, or synthetic images.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MARKET_ID = "260032"
MARKET_NAME = "REWE · Flughafenstr. 147, 44309 Dortmund-Brackel"
OFFICIAL_STORE = (
    "https://www.rewe.de/marktseite/dortmund/260032/"
    "rewe-markt-flughafenstr-147/"
)
OFFICIAL_OFFERS = (
    "https://www.rewe.de/angebote/dortmund/260032/"
    "rewe-flughafenstr-147/"
)


def build_rewe_booklet(day: date, *, today: date | None = None) -> dict:
    """Return only verifiable market identity and a non-booklet fallback."""
    if type(day) is not date:
        raise ValueError("Invalid REWE selected date")
    current = today if today is not None else datetime.now(ZoneInfo("Europe/Berlin")).date()
    if type(current) is not date:
        raise ValueError("Invalid REWE current date")
    monday = current - timedelta(days=current.weekday())
    if not monday <= day <= monday + timedelta(days=13):
        return {
            "state": "unavailable", "offers": [], "store_name": MARKET_NAME,
            "message": "Šim datumam nav pārbaudītu REWE bukleta lapu.",
        }
    return {
        "state": "external_link", "offers": [], "store_name": MARKET_NAME,
        "source_url": OFFICIAL_OFFERS,
        "link_label": "Atvērt REWE Brackel oficiālos piedāvājumus",
        "message": (
            "REWE oficiālā bukleta skatītājs pašlaik nav pieejams. "
            "Saite ved uz šī veikala piedāvājumiem, nevis pārbaudītām "
            "bukleta lapām. Veikala vietnes aktuālais saturs var "
            "neatbilst izvēlētajam datumam."
        ),
    }
