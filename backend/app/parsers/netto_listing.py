"""Netto 5659 HTML cards: public prices with card-local source evidence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.parsers.netto import NettoParserContext
from app.schemas import OfferCandidate, SourceChain

PARSER_VERSION = "netto-html-v1"
STORE_PATH = "/filialen/dortmund/rauschenbuschstr-1/5659"
LISTING_URL = "https://www.netto-online.de/filialangebote?stores_id=5659"
_ADDRESS = "Netto Filiale Rauschenbuschstr. 1 44319 Dortmund"
_RANGE = re.compile(r"gültig von (?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag), (\d{2}\.\d{2}\.\d{2}) - (?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag), (\d{2}\.\d{2}\.\d{2})", re.I)
_PRICE = re.compile(r"(ab|je)?\s*(\d+(?:[.,]\d{2}|[.,]?[-–—]))")


@dataclass(frozen=True)
class ListingResult:
    offers: list[OfferCandidate]
    rejected: list[dict[str, str]]
    card_count: int


def norm(value: str) -> str:
    return " ".join(value.split())


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "www.netto-online.de":
        raise ValueError("Netto URL host/scheme mismatch")
    if parsed.path.rstrip("/") not in {STORE_PATH, "/filialangebote"} and not (
        re.fullmatch(r"/filialangebote/[12]/\d+/?", parsed.path)
        or parsed.path.endswith("/ViewNettoStoreOffers-Show")
    ):
        raise ValueError("Unexpected Netto HTML source path")
    selected = parse_qs(parsed.query).get("stores_id")
    if selected is not None and selected != ["5659"]:
        raise ValueError("Netto URL store mismatch")


def validate_store(soup: BeautifulSoup) -> None:
    addresses = [norm(n.get_text(" ", strip=True)) for n in soup.select(".your-store__info__address")]
    if addresses != [_ADDRESS]:
        raise ValueError("Netto selected-store address mismatch")


def validity(text: str):
    match = _RANGE.search(norm(text))
    if match is None or len(_RANGE.findall(norm(text))) != 1:
        raise ValueError("Netto explicit validity range missing or ambiguous")
    start, end = [datetime.strptime(v, "%d.%m.%y").date() for v in match.groups()]
    if not 0 <= (end - start).days <= 6:
        raise ValueError("Netto invalid campaign duration")
    return start, end


def money(text: str) -> tuple[str, Decimal]:
    match = _PRICE.fullmatch(norm(text))
    if match is None:
        raise ValueError("Unsupported Netto price expression")
    value = re.sub(r"[.,]?[-–—]$", ".00", match[2]).replace(",", ".")
    price = Decimal(value)
    if price <= 0:
        raise ValueError("Netto price must be positive")
    return match[1] or "exact", price


def one(node: Tag, selector: str) -> Tag:
    nodes = node.select(selector)
    if len(nodes) != 1:
        raise ValueError(f"Netto expected one {selector}")
    return nodes[0]


def price_text(node: Tag) -> str:
    # Exclude only the footnote marker, never an app label or price qualifier.
    clone = BeautifulSoup(str(node), "html.parser")
    for marker in clone.select(".product__current-price--asterisk"):
        marker.decompose()
    return norm(clone.get_text("", strip=True))


def parse_listing(html: bytes, context: NettoParserContext) -> ListingResult:
    validate_url(context.source_url)
    if context.store_external_id != "5659" or context.collected_at.tzinfo is None:
        raise ValueError("Netto requires exact store and aware collection time")
    soup = BeautifulSoup(html, "html.parser")
    validate_store(soup)
    region = one(soup, "#region_store_offers_list")
    window = validity(one(region, ".offer__period").get_text(" ", strip=True))
    today = context.collected_at.astimezone(ZoneInfo("Europe/Berlin")).date()
    if window[1] < today or (window[0] - today).days > 7:
        raise ValueError("Netto stale or distant campaign")
    cards = region.select(".js-store-product-tile")
    if not cards:
        raise ValueError("Netto empty listing")
    offers, rejected, seen = [], [], set()
    for index, card in enumerate(cards):
        sku = card.get("data-ff-id", "")
        if not isinstance(sku, str) or not sku or sku in seen:
            raise ValueError("Netto missing or duplicate card SKU")
        seen.add(sku)
        try:
            link = urlparse(one(card, "a.js-add-to-wishlist[href]")["href"])
            if link.scheme != "https" or link.netloc != "www.netto-online.de" or not link.path.endswith("/ViewMMPWishlist-AddStoreArticle"):
                raise ValueError("Netto card metadata URL mismatch")
            query = parse_qs(link.query, keep_blank_values=True)
            if any(len(v) != 1 for v in query.values()):
                raise ValueError("Netto repeated card metadata key")
            fields = {k: v[0] for k, v in query.items()}
            if fields.get("SKU") != sku:
                raise ValueError("Netto SKU mismatch")
            title = norm(one(card, ".product__title").get_text(" ", strip=True))
            if not title or title != norm(fields.get("Name", "")):
                raise ValueError("Netto title mismatch")
            start, end = validity(fields.get("ValidityPeriod", ""))
            if (start, end) != window or datetime.fromisoformat(fields.get("ValidTo", "")).date() != end:
                raise ValueError("Netto card validity mismatch")
            kind, price = money(fields.get("Price", ""))
            if (kind, price) != money(price_text(one(card, ".grid-top-price .product__current-price"))):
                raise ValueError("Netto public price mismatch")
            if kind == "ab":
                raise ValueError("lower_bound_price")
            package = norm(one(card, ".product-property__bundle-text").get_text(" ", strip=True))
            if package != norm(fields.get("BundleText", "")):
                raise ValueError("Netto package mismatch")
            app_nodes = card.select(".grid-app-price .product__current-price")
            app = None
            if app_nodes or card.select(".has-app-price"):
                if len(app_nodes) != 1:
                    raise ValueError("Netto ambiguous app price")
                app_kind, app = money(price_text(app_nodes[0]))
                if app_kind == "ab" or app > price:
                    raise ValueError("Netto invalid app price")
            image = fields.get("Image", "")
            if image != one(card, ".product__img-wrapper > img").get("src") or urlparse(image).netloc != "www.netto-online.de" or urlparse(image).scheme != "https":
                raise ValueError("Netto image mismatch")
            unit, unit_label, mode = None, None, None
            if package in {"pro kg", "pro 100 g", "pro l", "pro 100 ml"}:
                unit, unit_label, mode = price, package[4:].replace(" ", ""), "unit_price_only"
            reference = card.select(".grid-top-price .product__old-price")
            reference_text = norm(reference[0].get_text(" ", strip=True)) if len(reference) == 1 else None
            regular = None
            if reference_text and reference_text.startswith("statt "):
                ref_kind, ref_price = money(reference_text[6:])
                if ref_kind == "exact" and ref_price > price:
                    regular = ref_price
            offers.append(OfferCandidate(
                source_chain=SourceChain.NETTO, source_store_external_id="5659",
                source_store_name=context.store_name, source_offer_id=f"{sku}:{start}:{end}",
                product_name_raw=title, description_raw=fields.get("Text") or None,
                package_text_raw=package or None, price_eur=price,
                regular_price_eur=regular, unit_price_eur=unit, unit_label=unit_label,
                pricing_mode=mode, app_price_eur=app, requires_app=False,
                valid_from=start, valid_until=end,
                app_valid_from=start if app is not None else None,
                app_valid_until=end if app is not None else None,
                source_url=context.source_url, source_image_url=image,
                snapshot_id=context.snapshot_id, collected_at=context.collected_at,
                parser_version=PARSER_VERSION,
                raw_payload={"sku": sku, "fields": fields, "reference_price_text": reference_text},
            ))
        except (ValueError, KeyError) as exc:
            rejected.append({"sku": sku, "card_index": str(index), "reason": str(exc)})
    return ListingResult(offers, rejected, len(cards))
