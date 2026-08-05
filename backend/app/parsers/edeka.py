from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.schemas import OfferCandidate, SourceChain

PARSER_VERSION = "edeka-v1"

_OFFER_FRAGMENT_RE = re.compile(
    r"^angebot-(?P<offer_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_VALID_FROM_RE = re.compile(
    r"Gültig\s+ab\s+(?P<value>\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
_VALID_UNTIL_RE = re.compile(
    r"Alle\s+Angebote\s+gültig\s+bis"
    r"(?:\s+[A-Za-zÄÖÜäöüß]+,)?\s+den\s+"
    r"(?P<value>\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
_FESTPREIS_RE = re.compile(
    r"Festpreis\s+von\s+(?P<price>\d{1,4}(?:[.,]\d{1,2})?)\s*€",
    re.IGNORECASE,
)
_RABATTIERTER_PREIS_RE = re.compile(
    r"Rabattierter\s+Preis\s+von\s+"
    r"(?P<price>\d{1,4}(?:[.,]\d{1,2})?)\s*€",
    re.IGNORECASE,
)
_APP_PREIS_RE = re.compile(
    r"App-Preis\s+von\s+(?P<price>\d{1,4}(?:[.,]\d{1,2})?)\s*€",
    re.IGNORECASE,
)
_TITLE_PREFIX_RE = re.compile(r"^\s*Angebot:\s*", re.IGNORECASE)
_LOCAL_TZ = ZoneInfo("Europe/Berlin")
_MAX_CAMPAIGN_LENGTH_DAYS = 7


@dataclass(frozen=True)
class EdekaParserContext:
    snapshot_id: UUID
    source_url: str
    collected_at: datetime
    public_market_id: str
    internal_market_id: str
    store_name: str


def _norm(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        result = Decimal(value.replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result.quantize(Decimal("0.01"))


def _date_de(value: str) -> date:
    day, month, year = value.split(".")
    return date(int(year), int(month), int(day))


def _validate_context(context: EdekaParserContext) -> None:
    public_market_id = context.public_market_id.strip()
    internal_market_id = context.internal_market_id.strip()
    store_name = context.store_name.strip()

    if not public_market_id:
        raise ValueError("EDEKA parser requires public_market_id")
    if not internal_market_id:
        raise ValueError("EDEKA parser requires internal_market_id")
    if not store_name:
        raise ValueError("EDEKA parser requires store_name")
    if context.collected_at.tzinfo is None or context.collected_at.utcoffset() is None:
        raise ValueError("EDEKA parser requires timezone-aware collected_at")

    parsed = urlparse(context.source_url)
    expected_path = f"/maerkte/{public_market_id}/angebote/"
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.casefold() != "www.edeka.de"
        or parsed.path != expected_path
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise ValueError(
            "EDEKA parser source_url is not bound to the configured public market "
            f"{public_market_id}: {context.source_url}"
        )


def _single_page_date(
    text: str,
    pattern: re.Pattern[str],
    *,
    label: str,
) -> date:
    values = {match.group("value") for match in pattern.finditer(text)}
    if len(values) != 1:
        raise ValueError(
            f"EDEKA expected exactly one distinct {label} date, found "
            f"{len(values)}: {sorted(values)}"
        )
    return _date_de(next(iter(values)))


def _page_validity(soup: BeautifulSoup) -> tuple[date, date]:
    text = _norm(soup.get_text(" ", strip=True))
    valid_from = _single_page_date(text, _VALID_FROM_RE, label="valid_from")
    valid_until = _single_page_date(text, _VALID_UNTIL_RE, label="valid_until")
    if valid_until < valid_from:
        raise ValueError("EDEKA valid_until is earlier than valid_from")
    if (valid_until - valid_from).days + 1 > _MAX_CAMPAIGN_LENGTH_DAYS:
        raise ValueError(
            "EDEKA campaign window is implausibly long: "
            f"{valid_from}..{valid_until}"
        )
    return valid_from, valid_until


def _validate_campaign_freshness(
    context: EdekaParserContext,
    valid_from: date,
    valid_until: date,
) -> None:
    reference_date = context.collected_at.astimezone(_LOCAL_TZ).date()
    if not valid_from <= reference_date <= valid_until:
        raise ValueError(
            "EDEKA campaign window does not cover the collection date; "
            "refusing stale or future catalogue: "
            f"collected={reference_date} campaign={valid_from}..{valid_until}"
        )


def _offer_id_from_href(href: str, source_url: str) -> str | None:
    parsed_href = urlparse(href)
    match = _OFFER_FRAGMENT_RE.fullmatch(parsed_href.fragment)
    if match is None:
        return None

    source_page = urlparse(source_url)
    resolved = urlparse(urljoin(source_url, href))
    if (
        resolved.scheme.casefold() != source_page.scheme.casefold()
        or resolved.netloc.casefold() != source_page.netloc.casefold()
        or resolved.path != source_page.path
        or resolved.query != source_page.query
    ):
        raise ValueError(
            "EDEKA offer fragment points outside the configured source page: "
            f"{href}"
        )

    return match.group("offer_id").lower()


def _price_fields(
    article: Tag,
) -> tuple[Decimal, Decimal | None, bool, list[str]]:
    labels = [
        _norm(node.get_text(" ", strip=True))
        for node in article.select(".sr-only")
        if _norm(node.get_text(" ", strip=True))
    ]

    festpreis: Decimal | None = None
    rabattierter_preis: Decimal | None = None
    app_preis: Decimal | None = None

    for label in labels:
        if festpreis is None:
            match = _FESTPREIS_RE.search(label)
            if match:
                festpreis = _decimal(match.group("price"))
        if rabattierter_preis is None:
            match = _RABATTIERTER_PREIS_RE.search(label)
            if match:
                rabattierter_preis = _decimal(match.group("price"))
        if app_preis is None:
            match = _APP_PREIS_RE.search(label)
            if match:
                app_preis = _decimal(match.group("price"))

    # Conservative v1 contract:
    # - Festpreis is the non-app weekly offer price when present.
    # - "Rabattierter Preis" is also an explicitly labelled non-app sale price.
    # - App-Preis is stored separately when present.
    # - No discount-percent or regular-price inference is made.
    # - Only a card with no labelled non-app price is requires_app=True.
    non_app_price = festpreis or rabattierter_preis
    if non_app_price is not None:
        return non_app_price, app_preis, False, labels
    if app_preis is not None:
        return app_preis, app_preis, True, labels

    raise ValueError(
        "EDEKA offer card has no Festpreis, Rabattierter Preis or App-Preis"
    )


def _description(article: Tag) -> str | None:
    for node in article.find_all("p"):
        classes = set(node.get("class") or [])
        if "line-clamp-2" in classes or "line-clmap-2" in classes:
            value = _norm(node.get_text(" ", strip=True))
            return value or None
    return None


def _image_rank(image: Tag) -> tuple[int, int]:
    src = str(image.get("src") or "")
    filename = urlparse(src).path.rsplit("/", 1)[-1].casefold()
    classes = set(image.get("class") or [])

    score = 0
    if "logo" in filename or filename.startswith("log_"):
        score -= 100
    if "aspect-square" in classes:
        score += 20
    if "object-contain" in classes:
        score += 10

    try:
        width = int(str(image.get("width") or "0"))
    except ValueError:
        width = 0

    return score, width


def _product_image(article: Tag, source_url: str) -> str | None:
    images = [
        image
        for image in article.find_all("img", src=True)
        if "offer-images.api.edeka/" in str(image.get("src") or "")
    ]
    if not images:
        return None

    selected = max(images, key=_image_rank)
    src = str(selected.get("src") or "").strip()
    filename = urlparse(src).path.rsplit("/", 1)[-1].casefold()

    # Do not promote a known logo-only asset into source_image_url.
    if "logo" in filename or filename.startswith("log_"):
        return None

    return urljoin(source_url, src)


def parse_edeka_html(
    html: bytes | str,
    context: EdekaParserContext,
) -> list[OfferCandidate]:
    _validate_context(context)

    soup = BeautifulSoup(html, "html.parser")
    page_title = _norm(soup.title.get_text(" ", strip=True)) if soup.title else ""
    if context.store_name.casefold() not in page_title.casefold():
        raise ValueError(
            f"EDEKA page title is not bound to {context.store_name!r}: "
            f"{page_title!r}"
        )

    valid_from, valid_until = _page_validity(soup)
    _validate_campaign_freshness(
        context,
        valid_from,
        valid_until,
    )

    offers: list[OfferCandidate] = []
    seen_offer_ids: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        source_offer_id = _offer_id_from_href(href, context.source_url)
        if source_offer_id is None or source_offer_id in seen_offer_ids:
            continue

        article = anchor.find_parent("article")
        if article is None:
            raise ValueError(
                f"EDEKA offer fragment is not inside an article: "
                f"{source_offer_id}"
            )

        dialog_id = f"dialog-angebot-{source_offer_id}"
        if soup.find("dialog", id=dialog_id) is None:
            raise ValueError(
                f"EDEKA offer fragment has no matching dialog: "
                f"{source_offer_id}"
            )

        raw_title = _norm(anchor.get_text(" ", strip=True))
        product_name = _TITLE_PREFIX_RE.sub("", raw_title).strip()
        if not product_name:
            raise ValueError(
                f"EDEKA offer has blank product name: {source_offer_id}"
            )

        price_eur, app_price_eur, requires_app, price_labels = (
            _price_fields(article)
        )
        description = _description(article)
        image_url = _product_image(article, context.source_url)

        offers.append(
            OfferCandidate(
                source_chain=SourceChain.EDEKA,
                # Hermes Deals active-store filtering uses the public/stable
                # store external ID from source configuration. For Patzer this
                # is the official URL ID 071897, NOT EDEKA's internal favorite
                # market cookie ID 587881.
                source_store_external_id=context.public_market_id,
                source_store_name=context.store_name,
                source_offer_id=source_offer_id,
                product_name_raw=product_name,
                brand_raw=None,
                description_raw=description,
                package_text_raw=None,
                price_eur=price_eur,
                regular_price_eur=None,
                unit_price_eur=None,
                unit_label=None,
                discount_percent=None,
                app_price_eur=app_price_eur,
                requires_app=requires_app,
                coupon_required=False,
                valid_from=valid_from,
                valid_until=valid_until,
                source_url=context.source_url,
                source_image_url=image_url,
                snapshot_id=context.snapshot_id,
                collected_at=context.collected_at,
                parser_version=PARSER_VERSION,
                raw_payload={
                    "public_market_id": context.public_market_id,
                    "internal_market_id": context.internal_market_id,
                    "fragment_href": href,
                    "dialog_id": dialog_id,
                    "raw_title": raw_title,
                    "price_labels": price_labels,
                    "description": description,
                    "image_selection": (
                        "product_candidate" if image_url else "none_or_logo_only"
                    ),
                },
            )
        )
        seen_offer_ids.add(source_offer_id)

    if not offers:
        raise ValueError("EDEKA parser found zero valid offer cards")

    return offers


def parse_edeka_snapshot(
    path: Path,
    context: EdekaParserContext,
) -> list[OfferCandidate]:
    return parse_edeka_html(path.read_bytes(), context)
