from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from uuid import UUID

from bs4 import BeautifulSoup

from app.schemas import OfferCandidate, SourceChain

PARSER_VERSION = "netto-v1"

_SECTION_START = "filial-angebote"
_SECTION_END = "aktuelle prospekte"
_CARD_MARKERS = {"filiale", "filiale & shop"}
_IGNORE_LINES = {
    "zu den angeboten",
    "alle filialangebote ansehen",
    "knüller der woche",
    "obst & gemüse",
    "backstube",
    "kühlregal & tiefkühlung",
    "getränke",
    "super wochenende",
}

_PRICE_TOKEN_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?|\d{1,4}[.,]?[-–—])(?=\s*\*?|\s|$)")
_UNIT_RE = re.compile(
    r"^(?P<low>\d+(?:[.,]\d+)?)"
    r"(?:\s*[-–—]\s*(?P<high>\d+(?:[.,]\d+)?))?"
    r"\s*/\s*(?P<unit>kg|g|l|ml|stück|100\s*g|100\s*ml)$",
    re.IGNORECASE,
)
_DISCOUNT_RE = re.compile(r"^-?\s*(?:bis\s+zu\s*)?(?P<pct>\d{1,3})\s*%$", re.IGNORECASE)
_PACKAGE_RE = re.compile(
    r"(?P<package>"
    r"(?:\d+\s*x\s*)?\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|blatt)"
    r"(?:\s*[-–—]\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|blatt))?"
    r"(?:\s+(?:schale|packung|beutel|dose|flasche))?"
    r"|\d+\s*stück"
    r"|stück"
    r")\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NettoParserContext:
    snapshot_id: UUID
    source_url: str
    collected_at: datetime
    store_external_id: str | None = None
    store_name: str | None = None


def _norm(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def _decimal(value: str) -> Decimal | None:
    cleaned = value.strip().replace("€", "").replace("*", "").replace(",", ".")
    # German advertising often renders whole-euro prices as "1.–" / "1.-".
    cleaned = re.sub(r"[.\-–—]+$", ".00", cleaned)
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    return result.quantize(Decimal("0.01"))


def _price_tokens(line: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in _PRICE_TOKEN_RE.finditer(line):
        value = _decimal(match.group(1))
        if value is not None:
            values.append(value)
    return values


def _extract_section(lines: list[str]) -> list[str]:
    lowered = [line.casefold() for line in lines]
    end_candidates = [i for i, value in enumerate(lowered) if value == _SECTION_END]
    if not end_candidates:
        raise ValueError("Netto section end 'Aktuelle Prospekte' not found")
    end = end_candidates[0]

    starts = [i for i, value in enumerate(lowered[:end]) if value == _SECTION_START]
    if not starts:
        raise ValueError("Netto section start 'Filial-Angebote' not found")
    # The navigation can contain a similarly named item; the real content heading is
    # the last exact occurrence before 'Aktuelle Prospekte'.
    start = starts[-1]
    if start >= end:
        raise ValueError("Netto offer section boundaries are invalid")
    return lines[start + 1 : end]


def _split_cards(section: Iterable[str]) -> list[list[str]]:
    cards: list[list[str]] = []
    current: list[str] | None = None
    for raw_line in section:
        line = _norm(raw_line)
        folded = line.casefold().lstrip("* ")
        if folded in _CARD_MARKERS:
            if current:
                cards.append(current)
            current = []
            continue
        if current is not None:
            current.append(line)
    if current:
        cards.append(current)
    return cards


def _clean_card(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        value = _norm(line)
        if not value:
            continue
        folded = value.casefold().lstrip("* ")
        if folded in _IGNORE_LINES:
            continue
        result.append(value)
    return result


def _find_price(lines: list[str]) -> tuple[Decimal | None, Decimal | None, int | None]:
    discount: int | None = None
    regular: Decimal | None = None
    current: Decimal | None = None

    for line in lines:
        match = _DISCOUNT_RE.match(_norm(line))
        if match:
            discount = min(int(match.group("pct")), 100)

    # Prefer a line explicitly containing UVP/statt; otherwise use the last
    # standalone price-like line ("Aktion" cards).
    for line in reversed(lines):
        folded = line.casefold()
        values = _price_tokens(line)
        if not values:
            continue
        if "uvp" in folded or "statt" in folded:
            if len(values) >= 2:
                regular, current = values[-2], values[-1]
            else:
                current = values[-1]
            break
        # Unit-price and descriptive lines should not become the sales price.
        if "/ kg" in folded or "/ l" in folded or "/ g" in folded or "/ ml" in folded:
            continue
        if "einzelpreis" in folded or "pfand" in folded or "% vol" in folded:
            continue
        current = values[-1]
        break

    return regular, current, discount


def _find_unit_price(lines: list[str]) -> tuple[Decimal | None, str | None]:
    for line in lines:
        match = _UNIT_RE.match(_norm(line))
        if not match:
            continue
        value = _decimal(match.group("low"))
        unit = match.group("unit").replace(" ", "").lower()
        # If the source exposes a range we keep the low end in the structured field
        # and preserve the complete source line in raw_payload.
        return value, unit
    return None, None


def _extract_package(product_name: str) -> str | None:
    match = _PACKAGE_RE.search(product_name)
    return _norm(match.group("package")) if match else None


def _description(lines: list[str], product_name: str) -> str | None:
    description: list[str] = []
    for line in lines:
        if line == product_name:
            continue
        folded = line.casefold()
        if _UNIT_RE.match(line) or _DISCOUNT_RE.match(line):
            continue
        if folded in {"aktion"} or "uvp" in folded or folded.startswith("statt "):
            continue
        if _price_tokens(line) and len(line) <= 20:
            continue
        description.append(line)
    return " | ".join(description) or None


def parse_netto_html(html: bytes | str, context: NettoParserContext) -> list[OfferCandidate]:
    soup = BeautifulSoup(html, "html.parser")
    lines = [_norm(value) for value in soup.stripped_strings]
    section = _extract_section(lines)
    raw_cards = _split_cards(section)

    offers: list[OfferCandidate] = []
    for card_index, raw_card in enumerate(raw_cards, start=1):
        card = _clean_card(raw_card)
        if not card:
            continue

        product_name = card[0]
        regular_price, current_price, discount = _find_price(card)
        if current_price is None or current_price <= 0:
            # Links/headings or malformed cards are ignored rather than inventing a price.
            continue

        unit_price, unit_label = _find_unit_price(card)
        package = _extract_package(product_name)
        stable_key = "|".join(
            [
                context.store_external_id or "",
                product_name.casefold(),
                str(current_price),
                package.casefold() if package else "",
            ]
        )
        source_offer_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:24]

        candidate = OfferCandidate(
            source_chain=SourceChain.NETTO,
            source_store_external_id=context.store_external_id,
            source_store_name=context.store_name,
            source_offer_id=source_offer_id,
            product_name_raw=product_name,
            description_raw=_description(card, product_name),
            package_text_raw=package,
            price_eur=current_price,
            regular_price_eur=regular_price,
            unit_price_eur=unit_price,
            unit_label=unit_label,
            discount_percent=discount,
            source_url=context.source_url,
            snapshot_id=context.snapshot_id,
            collected_at=context.collected_at,
            parser_version=PARSER_VERSION,
            raw_payload={
                "card_index": card_index,
                "lines": card,
            },
        )
        offers.append(candidate)

    if not offers:
        raise ValueError("Netto parser found zero valid offer cards")
    return offers


def parse_netto_snapshot(path: Path, context: NettoParserContext) -> list[OfferCandidate]:
    return parse_netto_html(path.read_bytes(), context)
