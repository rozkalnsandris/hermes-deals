from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence
from uuid import UUID
import argparse
import json
import os
import re


_WEEKDAY_TYPES = {
    "MONTAGS": "weekday_special",
    "DIENSTAGS": "weekday_special",
    "MITTWOCHS": "weekday_special",
    "DONNERSTAGS": "weekday_special",
    "FREITAGS": "weekday_special",
    "SAMSTAGS": "saturday_special",
    "SONNTAGS": "weekday_special",
}
_BANNER_WORDS = (
    "KRACHER",
    "SPAREN",
    "PREISKNÜLLER",
    "PREISKNALLER",
)
_DUPLICATED_TOKENS = (
    *tuple(_WEEKDAY_TYPES),
    "KRACHER",
    "SPAREN",
)
_DATE_RE = re.compile(
    r"gültig\s+am(?:\s+"
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)"
    r")?,?\s*(\d{1,2}\.\d{1,2}\.(?:\d{4}|\d{2}))",
    re.IGNORECASE,
)
_MILK_NAME_RE = re.compile(
    r"(Gutes\s+Land\s+Haltbare\s+Weide-?\s*milch\s+3[,.]5%\s+Fett)",
    re.IGNORECASE,
)
_MILK_FOOD_RE = re.compile(
    r"\b(?:weide-?\s*milch|haltbare\s+milch|vollmilch|"
    r"frischmilch|h[\s-]?milch|landmilch|trinkmilch)\b",
    re.IGNORECASE,
)
_NON_FOOD_MILK_RE = re.compile(
    r"\b(?:sonnenmilch|reinigungsmilch|körpermilch)\b",
    re.IGNORECASE,
)
_PACKAGE_RE = re.compile(
    r"(\d+)\s*x\s*(\d+(?:[,.]\d+)?)\s*(Liter|L|ml)\b",
    re.IGNORECASE,
)
_UNIT_PRICE_RE = re.compile(
    r"\((\d+(?:[,.]\d+)?)\s*/\s*l\)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"(?<!\d)(\d+(?:[,.]\d{1,2})?)(?!\d)")
_FOR_RE = re.compile(r"(\d+)\s*für\b", re.IGNORECASE)


@dataclass(frozen=True)
class NettoDailySpecialPage:
    page_number: int
    special_valid_on: date
    special_type: str
    special_source_text: str
    special_confidence: str
    special_source_geometry: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class NettoPdfTextBlock:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class NettoDailySpecialCandidate:
    source_offer_id: str
    product_name_raw: str
    package_text_raw: str
    price_eur: Decimal
    regular_price_eur: Decimal | None
    single_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    bundle_quantity: int | None
    valid_from: date
    valid_until: date
    is_daily_special: bool
    special_valid_on: date
    special_type: str
    special_source_text: str
    special_source_kind: str
    special_source_page: int
    special_confidence: str
    source_text_excerpt: str
    source_geometry: tuple[dict[str, object], ...] = ()
    unit_label: str | None = None
    pricing_mode: str = "fixed_package"
    app_price_eur: Decimal | None = None
    deposit_eur: Decimal | None = None


def _normalise_line(value: str) -> str:
    return " ".join(
        value.replace("\xa0", " ")
        .replace("−", "–")
        .split()
    )


def normalise_page_lines(text: str) -> list[str]:
    lines = [_normalise_line(line) for line in text.splitlines()]
    return [line for line in lines if line]


def normalise_banner_text(text: str) -> str:
    value = "\n".join(normalise_page_lines(text))
    for token in _DUPLICATED_TOKENS:
        value = re.sub(
            rf"(?:{re.escape(token)}){{2,}}",
            token,
            value,
            flags=re.IGNORECASE,
        )
    return value


def parse_german_date(value: str) -> date:
    day_text, month_text, year_text = value.split(".")
    year = int(year_text)
    if year < 100:
        year += 2000
    return date(year, int(month_text), int(day_text))


def detect_daily_special_page(
    text: str,
    page_number: int,
    blocks: Sequence[NettoPdfTextBlock] = (),
) -> NettoDailySpecialPage | None:
    normalised = normalise_banner_text(text)
    date_match = _DATE_RE.search(normalised)
    if not date_match:
        return None

    upper = normalised.upper()
    weekday = next(
        (token for token in _WEEKDAY_TYPES if token in upper),
        None,
    )
    has_banner = any(token in upper for token in _BANNER_WORDS)

    if weekday is None or not has_banner:
        return None

    source_lines = normalise_page_lines(normalised)
    date_index = next(
        (
            index
            for index, line in enumerate(source_lines)
            if date_match.group(1) in line
        ),
        len(source_lines) - 1,
    )
    start = max(0, date_index - 3)
    source_text = " | ".join(source_lines[start : date_index + 1])

    geometry: list[dict[str, object]] = []
    for block in blocks:
        block_upper = block.text.upper()
        if (
            weekday in block_upper
            or "KRACHER" in block_upper
            or date_match.group(1) in block.text
        ):
            geometry.append(
                {
                    "role": "daily_banner_or_date",
                    "bbox": [block.x0, block.y0, block.x1, block.y1],
                    "text": _normalise_line(block.text)[:300],
                }
            )

    return NettoDailySpecialPage(
        page_number=page_number,
        special_valid_on=parse_german_date(date_match.group(1)),
        special_type=_WEEKDAY_TYPES[weekday],
        special_source_text=source_text[:300],
        special_confidence="high",
        special_source_geometry=tuple(geometry),
    )


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "."))


def _line_decimal(line: str) -> Decimal | None:
    cleaned = (
        line.replace("€", "")
        .replace("*", "")
        .replace("–", "")
        .replace("—", "")
        .replace("-", "")
        .strip()
        .rstrip(".")
    )
    match = _NUMBER_RE.fullmatch(cleaned)
    if not match:
        return None
    return _decimal(match.group(1))


def _extract_single_price(
    lines: Sequence[str],
    anchor_index: int,
) -> Decimal | None:
    anchor = lines[anchor_index]
    inline = re.search(
        r"Einzelpreis:\s*(\d+(?:[,.]\d{1,2})?)",
        anchor,
        re.IGNORECASE,
    )
    if inline:
        return _decimal(inline.group(1))

    for line in lines[anchor_index + 1 : anchor_index + 4]:
        value = _line_decimal(line)
        if value is not None:
            return value
    return None


def _extract_bundle(
    lines: Sequence[str],
    start: int,
    end: int,
) -> tuple[int | None, Decimal | None, Decimal | None]:
    for index in range(start, end):
        quantity_match = _FOR_RE.search(lines[index])
        if not quantity_match:
            continue

        quantity = int(quantity_match.group(1))
        values: list[Decimal] = []
        for candidate_line in lines[max(start, index - 7) : index]:
            value = _line_decimal(candidate_line)
            if value is not None and value >= Decimal("1"):
                values.append(value)

        if not values:
            return quantity, None, None

        return quantity, min(values), max(values)

    return None, None, None


def _candidate_id(
    *,
    snapshot_id: str,
    page_number: int,
    valid_on: date,
    product_name: str,
    price: Decimal,
) -> str:
    payload = (
        f"netto|{snapshot_id}|{page_number}|{valid_on.isoformat()}|"
        f"{product_name.casefold()}|{price}"
    )
    return "netto-daily-" + sha256(payload.encode()).hexdigest()[:32]


def extract_food_milk_candidates(
    text: str,
    page: NettoDailySpecialPage,
    *,
    snapshot_id: str,
) -> list[NettoDailySpecialCandidate]:
    if not page:
        return []

    lines = normalise_page_lines(text)
    joined = " ".join(lines)

    if _NON_FOOD_MILK_RE.search(joined):
        joined_without_non_food = _NON_FOOD_MILK_RE.sub("", joined)
    else:
        joined_without_non_food = joined

    if not _MILK_FOOD_RE.search(joined_without_non_food):
        return []

    name_match = _MILK_NAME_RE.search(joined)
    if not name_match:
        return []

    milk_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.search(r"milch", line, re.IGNORECASE)
            and not _NON_FOOD_MILK_RE.search(line)
        ),
        None,
    )
    if milk_index is None:
        return []

    start = max(0, milk_index - 8)
    end = min(len(lines), milk_index + 18)
    window_lines = lines[start:end]
    window_text = " ".join(window_lines)

    package_match = _PACKAGE_RE.search(window_text)
    if not package_match:
        return []

    package_count = int(package_match.group(1))
    package_amount = package_match.group(2).replace(",", ".")
    package_unit = package_match.group(3)
    package_text = (
        f"{package_count} x {package_amount.rstrip('0').rstrip('.')} "
        f"{package_unit}"
    )

    unit_price_match = _UNIT_PRICE_RE.search(window_text)
    unit_price = (
        _decimal(unit_price_match.group(1))
        if unit_price_match
        else None
    )

    single_anchor = next(
        (
            index
            for index in range(start, end)
            if "einzelpreis" in lines[index].casefold()
        ),
        None,
    )
    single_price = (
        _extract_single_price(lines, single_anchor)
        if single_anchor is not None
        else None
    )

    quantity, bundle_price, regular_bundle_price = _extract_bundle(
        lines,
        start,
        end,
    )

    primary_price = bundle_price or single_price
    if primary_price is None:
        return []

    product_name = re.sub(
        r"\s+",
        " ",
        name_match.group(1).replace("Weide- milch", "Weidemilch"),
    )
    product_name = product_name.replace(",", ".")

    source_excerpt = " | ".join(window_lines)[:1000]

    return [
        NettoDailySpecialCandidate(
            source_offer_id=_candidate_id(
                snapshot_id=snapshot_id,
                page_number=page.page_number,
                valid_on=page.special_valid_on,
                product_name=product_name,
                price=primary_price,
            ),
            product_name_raw=product_name,
            package_text_raw=package_text,
            price_eur=primary_price,
            regular_price_eur=regular_bundle_price,
            single_price_eur=single_price,
            unit_price_eur=unit_price,
            bundle_quantity=quantity,
            valid_from=page.special_valid_on,
            valid_until=page.special_valid_on,
            is_daily_special=True,
            special_valid_on=page.special_valid_on,
            special_type=page.special_type,
            special_source_text=page.special_source_text,
            special_source_kind="prospect_pdf_page",
            special_source_page=page.page_number,
            special_confidence=page.special_confidence,
            source_text_excerpt=source_excerpt,
        )
    ]


_PACKAGE_MARKER_RE = re.compile(
    r"(?i)(?:"
    r"(?:\d+\s*x\s*)?\d+(?:[.,]\d+)?\s*(?:kg|g|ml|liter|l)"
    r"(?:\s*[–-]\s*\d+(?:[.,]\d+)?\s*(?:kg|g|ml|liter|l))?"
    r"|stück"
    r")"
)
_UNIT_PRICE_RE = re.compile(
    r"\((\d+(?:[.,]\d+)?)\s*/\s*(kg|g|l|ml|stück)\)",
    re.IGNORECASE,
)
_DESCRIPTOR_START_RE = re.compile(
    r"(?i)^(?:versch\.?|sorten\b|deutschland\b|portugal\b|"
    r"kl\.\s*[ivx]+\b|gekühlt\b|tiefgekühlt\b|mariniert\b|"
    r"mit\b|vakuum|ca\.\s*\d|zzgl\.|0\s*[–-])"
)
_PRIMARY_PRICE_RE = re.compile(
    r"^\s*(\d+(?:[.,](?:\d{1,2}|[–-]))?)\s*\*?\s*$"
)
_DISCOUNT_RE = re.compile(r"[–-]\s*\d{1,3}%")
_DEPOSIT_RE = re.compile(
    r"(?:zzgl\.?\s*)?Pfand\s*(\d+(?:[,.]\d{1,2})?)",
    re.IGNORECASE,
)


def _clean_pdf_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _price_decimal(value: str) -> Decimal | None:
    cleaned = value.replace("–", "-").replace(",", ".").strip()
    if re.fullmatch(r"\d+\.\-", cleaned):
        cleaned = cleaned[:-1] + "00"
    if not re.fullmatch(r"\d+\.\d{1,2}", cleaned):
        return None
    return Decimal(cleaned).quantize(Decimal("0.01"))


def _primary_price(block: NettoPdfTextBlock) -> Decimal | None:
    match = _PRIMARY_PRICE_RE.fullmatch(_clean_pdf_text(block.text))
    return _price_decimal(match.group(1)) if match else None


def _block_distance(
    left: NettoPdfTextBlock,
    right: NettoPdfTextBlock,
) -> float:
    horizontal = max(left.x0 - right.x1, right.x0 - left.x1, 0.0)
    vertical = max(left.y0 - right.y1, right.y0 - left.y1, 0.0)
    return (horizontal**2 + vertical**2) ** 0.5


def _product_name_and_package(
    block: NettoPdfTextBlock,
) -> tuple[str, str] | None:
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    package_index = next(
        (
            index
            for index, line in enumerate(lines)
            if (
                (match := _PACKAGE_MARKER_RE.search(line)) is not None
                and (
                    match.group(0).casefold() != "stück"
                    or re.fullmatch(r"(?i)stück", line) is not None
                )
            )
        ),
        None,
    )
    if package_index is None:
        return None

    name_lines: list[str] = []
    for line in lines[:package_index]:
        if _DESCRIPTOR_START_RE.search(line):
            break
        name_lines.append(line)
    if not name_lines:
        return None

    name = name_lines[0]
    for line in name_lines[1:]:
        if name.endswith("-"):
            previous = name[:-1]
            name = (
                previous + line
                if line[:1].islower()
                else previous + "-" + line
            )
        else:
            name += " " + line
    name = _clean_pdf_text(name)
    # FitZ may split a package range between adjacent lines, for example
    # ``0,65 Liter – 1`` and ``Liter``.  Search the cleaned tail instead of
    # only the first package line so the exact source range is preserved.
    package_source = _clean_pdf_text(" ".join(lines[package_index:]))
    package_match = _PACKAGE_MARKER_RE.search(package_source)
    if package_match is None:
        return None
    package = _clean_pdf_text(package_match.group(0))
    if not name or not package:
        return None
    return name, package


def _nearby_price_confirmation(
    primary: NettoPdfTextBlock,
    blocks: Sequence[NettoPdfTextBlock],
) -> list[NettoPdfTextBlock]:
    result: list[NettoPdfTextBlock] = []
    for block in blocks:
        if _block_distance(primary, block) > 125:
            continue
        text = _clean_pdf_text(block.text)
        if (
            "UVP" in text.upper()
            or _DISCOUNT_RE.search(text)
            or text.casefold() == "aktion"
        ):
            result.append(block)
    return result


def _regular_price(
    primary: NettoPdfTextBlock,
    confirmations: Sequence[NettoPdfTextBlock],
    nearby_blocks: Sequence[NettoPdfTextBlock],
    *,
    inline_primary: bool,
) -> Decimal | None:
    values: list[Decimal] = []
    for block in confirmations:
        if not inline_primary and (
            block.x0 < primary.x0 - 10
            or block.x0 > primary.x1 + 50
            or abs(block.y0 - primary.y0) > 90
        ):
            continue
        for raw in re.findall(r"\d+(?:[.,]\d{1,2})", block.text):
            value = _price_decimal(raw)
            if value is not None:
                values.append(value)
    primary_value = _primary_price(primary)
    candidates = [value for value in values if value != primary_value]
    if candidates:
        return max(candidates)

    fallback: list[tuple[float, Decimal]] = []
    for block in nearby_blocks:
        value = _primary_price(block)
        if (
            value is None
            or value == primary_value
            or value <= primary_value
            or block.x0 < primary.x0 + 10
            or abs(block.y0 - primary.y0) > 80
        ):
            continue
        fallback.append((_block_distance(primary, block), value))
    return min(fallback)[1] if fallback else None


def _inline_product_price(block: NettoPdfTextBlock) -> Decimal | None:
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    for line in reversed(lines):
        value = _primary_price(
            NettoPdfTextBlock(line, block.x0, block.y0, block.x1, block.y1)
        )
        if value is not None:
            return value
    return None


def _unit_price(
    block: NettoPdfTextBlock,
) -> tuple[Decimal | None, str | None]:
    match = _UNIT_PRICE_RE.search(block.text)
    if match is None:
        return None, None
    value = _price_decimal(match.group(1))
    return value, match.group(2).casefold()


def _deposit_price(block: NettoPdfTextBlock) -> Decimal | None:
    match = _DEPOSIT_RE.search(block.text)
    return _decimal(match.group(1)) if match else None


def _standalone_prices(block: NettoPdfTextBlock) -> list[Decimal]:
    values: list[Decimal] = []
    for raw_line in block.text.splitlines():
        line = _clean_pdf_text(raw_line)
        value = _primary_price(
            NettoPdfTextBlock(line, block.x0, block.y0, block.x1, block.y1)
        )
        if value is not None:
            values.append(value)
    return values


_APP_UNIT_PRICE_RE = re.compile(
    r"\((\d+(?:[.,]\d+)?)"
    r"(?:\s*[–-]\s*(\d+(?:[.,]\d+)?))?"
    r"\s*/\s*(kg|g|l|ml|liter|stück)\)",
    re.IGNORECASE,
)
_PACKAGE_VALUE_RE = re.compile(
    r"(?i)(?:\d+\s*x\s*)?"
    r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|liter|l)"
    r"(?:\s*[–-]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|liter|l))?"
)


def _normalised_amount(value: Decimal, unit: str) -> tuple[Decimal, str]:
    key = unit.casefold()
    if key == "kg":
        return value, "kg"
    if key == "g":
        return value / Decimal("1000"), "kg"
    if key in {"liter", "l"}:
        return value, "l"
    if key == "ml":
        return value / Decimal("1000"), "l"
    return value, key


def _package_amounts(package_text: str) -> tuple[list[Decimal], str | None]:
    match = _PACKAGE_VALUE_RE.search(package_text)
    if match is None:
        return [], None
    first, unit = _normalised_amount(_decimal(match.group(1)), match.group(2))
    amounts = [first]
    if match.group(3) is not None and match.group(4) is not None:
        second, second_unit = _normalised_amount(
            _decimal(match.group(3)),
            match.group(4),
        )
        if second_unit != unit:
            return [], None
        amounts.append(second)
    return amounts, unit


def _app_unit_prices(block: NettoPdfTextBlock) -> tuple[list[Decimal], str | None]:
    match = _APP_UNIT_PRICE_RE.search(_clean_pdf_text(block.text))
    if match is None:
        return [], None
    values = [_decimal(match.group(1))]
    if match.group(2) is not None:
        values.append(_decimal(match.group(2)))
    unit = match.group(3).casefold()
    if unit == "liter":
        unit = "l"
    return values, unit


def _app_price_math_matches(
    package_text: str,
    app_price: Decimal,
    support_block: NettoPdfTextBlock,
) -> bool:
    amounts, package_unit = _package_amounts(package_text)
    unit_prices, unit = _app_unit_prices(support_block)
    if not amounts or not unit_prices or package_unit != unit:
        return False
    expected = sorted(app_price / amount for amount in amounts if amount > 0)
    observed = sorted(unit_prices)
    if len(expected) != len(observed):
        return False
    tolerance = Decimal("0.02")
    return all(abs(left - right) <= tolerance for left, right in zip(expected, observed))


def _netto_plus_price(
    product_block: NettoPdfTextBlock,
    primary_block: NettoPdfTextBlock,
    package_text: str,
    base_price: Decimal,
    blocks: Sequence[NettoPdfTextBlock],
) -> tuple[Decimal | None, tuple[NettoPdfTextBlock, ...]]:
    """Bind a Netto-plus price to the exact product card.

    On the immutable real PDF the yellow ``Netto plus`` label is artwork and
    is absent from FitZ text.  The price itself is a right-hand companion tile.
    We therefore require all of the following source-backed signals:

    * the candidate price is lower than the base price;
    * it sits immediately to the right of and vertically overlaps the base
      price tile; and
    * a same-tile unit-price line exactly agrees with the product package math.

    This binds Lillet 9.99 and Softlan 1.00 without leaking either value to a
    neighbouring card.
    """
    candidates: list[
        tuple[float, Decimal, NettoPdfTextBlock, NettoPdfTextBlock]
    ] = []
    for price_block in blocks:
        horizontal_gap = price_block.x0 - primary_block.x1
        if horizontal_gap < -5 or horizontal_gap > 80:
            continue
        vertical_overlap = min(primary_block.y1, price_block.y1) - max(
            primary_block.y0,
            price_block.y0,
        )
        if vertical_overlap < 5:
            continue
        if price_block.x0 < product_block.x0 + 35:
            continue
        for value in _standalone_prices(price_block):
            if value >= base_price:
                continue
            support_blocks = [price_block]
            support_blocks.extend(
                block
                for block in blocks
                if block is not price_block
                and block.x0 >= price_block.x0 - 15
                and block.x1 <= price_block.x1 + 35
                and _block_distance(price_block, block) <= 45
            )
            for support_block in support_blocks:
                if not _app_price_math_matches(
                    package_text,
                    value,
                    support_block,
                ):
                    continue
                score = horizontal_gap + abs(
                    (price_block.y0 + price_block.y1)
                    - (primary_block.y0 + primary_block.y1)
                ) / 2
                candidates.append(
                    (score, value, price_block, support_block)
                )

    if not candidates:
        return None, ()
    _, value, price_block, support_block = min(
        candidates,
        key=lambda row: (row[0], row[1]),
    )
    geometry = [price_block]
    if support_block is not price_block:
        geometry.append(support_block)
    return value, tuple(geometry)


def _geometry(role: str, block: NettoPdfTextBlock) -> dict[str, object]:
    return {
        "role": role,
        "bbox": [block.x0, block.y0, block.x1, block.y1],
        "text": _clean_pdf_text(block.text)[:600],
    }


def extract_geometry_candidates(
    blocks: Sequence[NettoPdfTextBlock],
    page: NettoDailySpecialPage | None,
    *,
    snapshot_id: str,
) -> list[NettoDailySpecialCandidate]:
    """Extract only cards whose product, price, and discount geometry agree.

    Netto's PDF content stream does not preserve card order.  Geometry is thus
    the binding between a product/package block and its nearby price tile.
    Missing any part of that binding omits the card rather than guessing.
    """
    if page is None:
        return []

    price_blocks = [
        (block, value)
        for block in blocks
        if (value := _primary_price(block)) is not None
    ]
    candidates: list[NettoDailySpecialCandidate] = []
    for product_block in blocks:
        product = _product_name_and_package(product_block)
        if product is None:
            continue
        product_name, package_text = product

        possible_prices = [
            (block, value)
            for block, value in price_blocks
            if block.x1 >= product_block.x1
            and block.x0 >= product_block.x0 + 15
            and block.y0 >= product_block.y0 - 5
        ]
        inline_primary = False
        if possible_prices:
            primary_block, price = min(
                possible_prices,
                key=lambda item: (
                    max(0.0, item[0].x0 - product_block.x1)
                    + max(0.0, item[0].y0 - product_block.y0) * 3
                ),
            )
        else:
            price = _inline_product_price(product_block)
            if price is None:
                continue
            primary_block = product_block
            inline_primary = True
        confirmations = _nearby_price_confirmation(primary_block, blocks)
        if not confirmations:
            continue
        nearby_blocks = [
            block for block in blocks
            if _block_distance(primary_block, block) <= 125
        ]

        unit_price, unit_label = _unit_price(product_block)
        pricing_mode = "fixed_package"
        if any(
            re.search(r"\bpro\s+kg\b", block.text, re.IGNORECASE)
            for block in nearby_blocks
        ):
            unit_price = price
            unit_label = "kg"
            pricing_mode = "unit_price_only"

        app_price, app_geometry = _netto_plus_price(
            product_block,
            primary_block,
            package_text,
            price,
            blocks,
        )
        deposit_price = _deposit_price(product_block)

        geometry = [_geometry("product", product_block)]
        geometry.append(_geometry("sale_price", primary_block))
        geometry.extend(_geometry("discount_or_regular", block) for block in confirmations)
        if app_geometry:
            geometry.append(_geometry("netto_plus_price", app_geometry[0]))
            geometry.extend(
                _geometry("netto_plus_unit_support", block)
                for block in app_geometry[1:]
            )
        source_excerpt = " | ".join(
            entry["text"] for entry in geometry
        )[:1000]
        candidates.append(
            NettoDailySpecialCandidate(
                source_offer_id=_candidate_id(
                    snapshot_id=snapshot_id,
                    page_number=page.page_number,
                    valid_on=page.special_valid_on,
                    product_name=product_name,
                    price=price,
                ),
                product_name_raw=product_name,
                package_text_raw=package_text,
                price_eur=price,
                regular_price_eur=_regular_price(
                    primary_block,
                    confirmations,
                    nearby_blocks,
                    inline_primary=inline_primary,
                ),
                single_price_eur=None,
                unit_price_eur=unit_price,
                bundle_quantity=None,
                valid_from=page.special_valid_on,
                valid_until=page.special_valid_on,
                is_daily_special=True,
                special_valid_on=page.special_valid_on,
                special_type=page.special_type,
                special_source_text=page.special_source_text,
                special_source_kind="prospect_pdf_page",
                special_source_page=page.page_number,
                special_confidence=page.special_confidence,
                source_text_excerpt=source_excerpt,
                source_geometry=tuple(geometry),
                unit_label=unit_label,
                pricing_mode=pricing_mode,
                app_price_eur=app_price,
                deposit_eur=deposit_price,
            )
        )
    return candidates


def extract_pdf_daily_special_candidates(
    pdf_path: Path,
    *,
    snapshot_id: str,
) -> list[tuple[NettoDailySpecialPage, list[NettoDailySpecialCandidate], str]]:
    import fitz

    result: list[tuple[NettoDailySpecialPage, list[NettoDailySpecialCandidate], str]] = []
    document = fitz.open(pdf_path)
    try:
        for page_number, pdf_page in enumerate(document, start=1):
            blocks = tuple(
                NettoPdfTextBlock(
                    text=block[4],
                    x0=float(block[0]),
                    y0=float(block[1]),
                    x1=float(block[2]),
                    y1=float(block[3]),
                )
                for block in pdf_page.get_text("blocks")
                if block[4].strip()
            )
            page_text = "\n".join(block.text for block in blocks)
            special_page = detect_daily_special_page(
                page_text,
                page_number,
                blocks,
            )
            if special_page is None:
                continue
            result.append(
                (
                    special_page,
                    extract_geometry_candidates(
                        blocks,
                        special_page,
                        snapshot_id=snapshot_id,
                    ),
                    sha256(page_text.encode()).hexdigest(),
                )
            )
    finally:
        document.close()
    return result


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime, UUID)):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def inspect_latest_netto_snapshot(output_path: Path) -> dict:
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])

    with engine.connect() as connection:
        default_mode = connection.execute(
            text("SHOW default_transaction_read_only")
        ).scalar_one()
        transaction_mode = connection.execute(
            text("SHOW transaction_read_only")
        ).scalar_one()

        if default_mode != "on" or transaction_mode != "on":
            raise RuntimeError("Shadow inspection session is not read-only")

        snapshot = connection.execute(
            text(
                """
                SELECT
                  id,
                  source_url,
                  final_url,
                  collected_at,
                  sha256,
                  snapshot_path,
                  strategy_hint
                FROM source_snapshots
                WHERE source_chain='netto'
                  AND scope='family_primary_netto'
                  AND success IS TRUE
                ORDER BY collected_at DESC
                LIMIT 1
                """
            )
        ).mappings().one()

    manifest_path = Path(snapshot["snapshot_path"])
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = sha256(manifest_bytes).hexdigest()

    if snapshot["sha256"] and manifest_sha != snapshot["sha256"]:
        raise RuntimeError("Latest Netto manifest SHA mismatch")

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    pdf_path = Path(manifest["prospect_pdf_path"])
    pdf_bytes = pdf_path.read_bytes()
    pdf_sha = sha256(pdf_bytes).hexdigest()

    if pdf_sha != manifest["prospect_pdf_sha256"]:
        raise RuntimeError("Immutable Netto prospect PDF SHA mismatch")

    pages: list[dict] = []
    candidates: list[NettoDailySpecialCandidate] = []

    for special_page, page_candidates, page_text_sha in (
        extract_pdf_daily_special_candidates(
            pdf_path,
            snapshot_id=str(snapshot["id"]),
        )
    ):
        candidates.extend(page_candidates)
        pages.append(
            {
                **asdict(special_page),
                "text_sha256": page_text_sha,
                "candidate_count": len(page_candidates),
            }
        )

    result = {
        "contract": {
            "mode": "read_only_shadow",
            "fail_closed": True,
            "default_transaction_read_only": default_mode,
            "transaction_read_only": transaction_mode,
            "parser_version": "netto-daily-special-geometry-v4",
        },
        "snapshot": {
            key: value for key, value in dict(snapshot).items()
        },
        "manifest": {
            "prospect_slug": manifest.get("prospect_slug"),
            "valid_from": manifest.get("valid_from"),
            "valid_until": manifest.get("valid_until"),
            "prospect_pdf_sha256": manifest.get(
                "prospect_pdf_sha256"
            ),
        },
        "immutable_files": {
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha,
            "pdf_path": str(pdf_path),
            "pdf_sha256": pdf_sha,
        },
        "daily_special_pages": pages,
        "candidates": [asdict(candidate) for candidate in candidates],
    }

    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=_json_value,
        ),
        encoding="utf-8",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )
    args = parser.parse_args(argv)

    result = inspect_latest_netto_snapshot(args.output)
    print(
        "DAILY_SPECIAL_PAGES="
        + str(len(result["daily_special_pages"]))
    )
    print("SHADOW_CANDIDATES=" + str(len(result["candidates"])))
    print("PASS netto_daily_special_shadow_runtime=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
