from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

from app.schemas import OfferCandidate, SourceChain

PARSER_VERSION = "aldi-nord-v1"

_NEXT_DATA_RE = re.compile(
    r"""<script[^>]+id=["']__NEXT_DATA__["'][^>]*>(.*?)</script>""",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class AldiNordParserContext:
    snapshot_id: UUID
    source_url: str
    collected_at: datetime


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not result.is_finite():
        return None
    return result


def _local_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _epoch_date(value: Any) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _first_http_url(value: Any) -> str | None:
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        return None

    if isinstance(value, dict):
        for key, nested in value.items():
            if (
                isinstance(nested, str)
                and nested.startswith(("http://", "https://"))
                and any(token in str(key).casefold() for token in ("url", "src", "image", "asset"))
            ):
                return nested
        for nested in value.values():
            found = _first_http_url(nested)
            if found:
                return found

    if isinstance(value, list):
        for nested in value:
            found = _first_http_url(nested)
            if found:
                return found

    return None


def _regular_price(current_price: dict[str, Any], sale_price: Decimal) -> Decimal | None:
    strike = current_price.get("strikePrice")
    candidates: list[Any] = []

    if isinstance(strike, dict):
        candidates.extend(
            strike.get(key)
            for key in ("strikePriceValue", "priceValue", "value")
        )
    else:
        candidates.append(strike)

    candidates.extend(
        current_price.get(key)
        for key in ("strikePriceValue", "regularPrice", "oldPrice")
    )

    for candidate in candidates:
        value = _decimal(candidate)
        if value is not None and value > sale_price:
            return value
    return None


def _unit_price(current_price: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    base_price = current_price.get("basePrice")
    if not isinstance(base_price, list) or not base_price:
        return None, None

    first = base_price[0]
    if not isinstance(first, dict):
        return None, None

    value = _decimal(first.get("basePriceValue"))
    if value is None or value <= 0:
        value = None

    raw_label = first.get("basePriceScale")
    label = str(raw_label).strip() if raw_label is not None else None
    if not label:
        label = None

    if value is None:
        label = None
    return value, label


def _validity(
    current_price: dict[str, Any],
    promotion_prices: Any,
) -> tuple[date | None, date | None]:
    promotion = (
        promotion_prices[0]
        if isinstance(promotion_prices, list)
        and promotion_prices
        and isinstance(promotion_prices[0], dict)
        else {}
    )

    valid_from = (
        _local_date(promotion.get("validFromLocalDate"))
        or _epoch_date(current_price.get("validFrom"))
    )
    valid_until = (
        _local_date(promotion.get("validUntilLocalDate"))
        or _epoch_date(current_price.get("validUntil"))
    )
    return valid_from, valid_until


def _extract_offer_map(html: bytes | str) -> dict[str, dict[str, Any]]:
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html

    match = _NEXT_DATA_RE.search(text)
    if not match:
        raise ValueError("ALDI __NEXT_DATA__ payload not found")

    try:
        next_data = json.loads(html_lib.unescape(match.group(1)).strip())
    except json.JSONDecodeError as exc:
        raise ValueError("ALDI __NEXT_DATA__ is not valid JSON") from exc

    page_props = ((next_data.get("props") or {}).get("pageProps") or {})
    api_data_raw = page_props.get("apiData")
    if isinstance(api_data_raw, str):
        try:
            api_data = json.loads(api_data_raw)
        except json.JSONDecodeError as exc:
            raise ValueError("ALDI pageProps.apiData is not valid JSON") from exc
    else:
        api_data = api_data_raw

    if not isinstance(api_data, list):
        raise ValueError("ALDI pageProps.apiData is not a list")

    offer_payloads = [
        item[1]
        for item in api_data
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and str(item[0]).upper() == "OFFER_GET"
            and isinstance(item[1], dict)
        )
    ]
    if len(offer_payloads) != 1:
        raise ValueError(
            f"ALDI expected exactly one OFFER_GET payload, found {len(offer_payloads)}"
        )

    response = offer_payloads[0].get("res")
    offer_map = response.get("algoliaDataMap") if isinstance(response, dict) else None
    if not isinstance(offer_map, dict):
        raise ValueError("ALDI OFFER_GET.res.algoliaDataMap is missing")

    result: dict[str, dict[str, Any]] = {}
    for map_key, raw in offer_map.items():
        if not isinstance(raw, dict):
            raise ValueError(f"ALDI offer map row is not an object: {map_key!r}")
        result[str(map_key)] = raw
    return result


def parse_aldi_nord_html(
    html: bytes | str,
    context: AldiNordParserContext,
) -> list[OfferCandidate]:
    offer_map = _extract_offer_map(html)
    offers: list[OfferCandidate] = []

    for map_key, raw in offer_map.items():
        object_id = str(raw.get("objectID") or "").strip()
        if not object_id:
            raise ValueError(f"ALDI offer has blank objectID for map key {map_key!r}")
        if object_id != map_key:
            raise ValueError(
                f"ALDI objectID/map-key mismatch: key={map_key!r} objectID={object_id!r}"
            )

        product_name = str(raw.get("name") or "").strip()
        if not product_name:
            raise ValueError(f"ALDI offer has blank name: {object_id}")

        current_price = raw.get("currentPrice")
        # The public next-week payload can contain catalogue rows that are not
        # currently priced offers. They are not invented into OfferCandidates.
        if current_price is None:
            continue
        if not isinstance(current_price, dict):
            raise ValueError(f"ALDI currentPrice is not an object: {object_id}")

        sale_price = _decimal(current_price.get("priceValue"))
        if sale_price is None or sale_price <= 0:
            raise ValueError(f"ALDI current price is invalid: {object_id}")

        valid_from, valid_until = _validity(
            current_price,
            raw.get("promotionPrices"),
        )
        # On the offers page, an undated product is not promoted into the
        # validated offer boundary.
        if valid_from is None or valid_until is None:
            continue

        unit_price, unit_label = _unit_price(current_price)
        brand = str(raw.get("brandName") or "").strip() or None
        description = str(raw.get("shortDescription") or "").strip() or None
        package = str(raw.get("salesUnit") or "").strip() or None

        offers.append(
            OfferCandidate(
                source_chain=SourceChain.ALDI_NORD,
                source_offer_id=object_id,
                product_name_raw=product_name,
                brand_raw=brand,
                description_raw=description,
                package_text_raw=package,
                price_eur=sale_price,
                regular_price_eur=_regular_price(current_price, sale_price),
                unit_price_eur=unit_price,
                unit_label=unit_label,
                valid_from=valid_from,
                valid_until=valid_until,
                source_url=context.source_url,
                source_image_url=_first_http_url(raw.get("assets")),
                snapshot_id=context.snapshot_id,
                collected_at=context.collected_at,
                parser_version=PARSER_VERSION,
                raw_payload=raw,
            )
        )

    if not offers:
        raise ValueError("ALDI parser found zero valid structured offers")
    return offers


def parse_aldi_nord_snapshot(
    path: Path,
    context: AldiNordParserContext,
) -> list[OfferCandidate]:
    return parse_aldi_nord_html(path.read_bytes(), context)
