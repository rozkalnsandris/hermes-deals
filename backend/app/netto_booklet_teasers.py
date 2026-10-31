"""Extract dated Netto booklet teasers from one already store-bound HTML page.

A teaser start is NOT a publication validity window or a product identity.
"""
from __future__ import annotations

from datetime import date, datetime
import html
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from bs4 import BeautifulSoup

from app.structured_source_shadow import NETTO_STORE_ID, extract_netto_direct_viewers

_START = re.compile(
    r"\bab\s+(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),?\s*"
    r"(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2}))\b",
    re.I,
)
_WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}
_SLUG_PATH = re.compile(r"/([A-Za-z0-9_-]+)/?")


def extract_netto_booklet_teaser_starts(store_html: str, store_id: str = NETTO_STORE_ID) -> dict[str, date]:
    """Bind official viewer slugs to dates only inside their own teaser cards.

    Missing dates stay unknown; conflicting slugs, dates and store IDs fail closed.
    Caller must separately verify the stored HTML SHA and selected-store cookie.
    """
    if store_id != NETTO_STORE_ID:
        raise ValueError("Netto booklet teaser requires store 5659")
    soup = BeautifulSoup(store_html, "html.parser")
    known = extract_netto_direct_viewers(store_html, store_id)
    starts: dict[str, date] = {}

    for card in soup.select(".prospekt-teaser-item"):
        slugs: set[str] = set()
        for anchor in card.select("a[href]"):
            url = urlsplit(html.unescape(unquote(str(anchor["href"]))))
            if (url.scheme, url.netloc) != ("https", "wochenprospekt.netto-online.de"):
                continue
            match = _SLUG_PATH.fullmatch(url.path)
            if match is None or url.fragment or url.username:
                continue
            query = parse_qsl(url.query, keep_blank_values=True, max_num_fields=20)
            for key in ("storeid", "stores_id"):
                selected = [value for name, value in query if name == key]
                if selected and selected != [store_id]:
                    raise ValueError("Netto booklet teaser store mismatch")
            slug = match.group(1)
            if slug in known:
                slugs.add(slug)

        if not slugs:
            continue
        if len(slugs) != 1:
            raise ValueError("Ambiguous Netto booklet teaser links")
        dates = _START.findall(card.get_text(" ", strip=True))
        if not dates:
            continue
        if len(dates) != 1:
            raise ValueError("Ambiguous Netto booklet teaser start date")
        weekday, raw_date = dates[0]
        fmt = "%d.%m.%Y" if len(raw_date.rsplit(".", 1)[-1]) == 4 else "%d.%m.%y"
        started = datetime.strptime(raw_date, fmt).date()
        if started.weekday() != _WEEKDAYS[weekday.casefold()]:
            raise ValueError("Netto booklet teaser weekday mismatch")
        slug = next(iter(slugs))
        if slug in starts and starts[slug] != started:
            raise ValueError("Conflicting Netto booklet teaser start dates")
        starts[slug] = started
    return dict(sorted(starts.items()))
