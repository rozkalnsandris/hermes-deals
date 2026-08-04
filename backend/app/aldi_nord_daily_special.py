from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import html as html_lib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from app.parsers.aldi_nord import (
    _decimal,
    _first_http_url,
    _regular_price,
    _unit_price,
)
from app.schemas import OfferCandidate, SourceChain


_PARSER_VERSION = "aldi-nord-daily-special-v1"
_NEXT_DATA_RE = re.compile(
    r"""<script[^>]+id=["']__NEXT_DATA__["'][^>]*>(.*?)</script>""",
    re.IGNORECASE | re.DOTALL,
)
_DAILY_LABEL_RE = re.compile(
    r"^Nur\s+(?:Mo|Di|Mi|Do|Fr|Sa|So)\.\s+"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.$"
)


class AldiNordDailySpecialError(RuntimeError):
    pass


@dataclass(frozen=True)
class AldiNordDailySpecialContext:
    snapshot_id: UUID
    snapshot_sha256: str
    source_url: str
    collected_at: datetime


def _verify_file(
    path_value: str,
    expected_sha256: str,
) -> Path:
    if not path_value:
        raise AldiNordDailySpecialError("ALDI Nord snapshot path is missing")
    if not expected_sha256 or len(expected_sha256) != 64:
        raise AldiNordDailySpecialError("ALDI Nord snapshot SHA is invalid")
    path = Path(path_value)
    if not path.is_file():
        raise AldiNordDailySpecialError(
            f"ALDI Nord snapshot file is missing: {path}"
        )
    actual = sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise AldiNordDailySpecialError(
            "ALDI Nord snapshot SHA mismatch: "
            f"expected={expected_sha256} actual={actual}"
        )
    return path


def _validate_source_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() != "www.aldi-nord.de"
        or parsed.path != "/angebote.html"
    ):
        raise AldiNordDailySpecialError(
            "ALDI Nord daily-special source is not the configured official "
            f"offers page: {source_url}"
        )


def _offer_response(html: bytes | str) -> dict[str, Any]:
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    match = _NEXT_DATA_RE.search(text)
    if match is None:
        raise AldiNordDailySpecialError("ALDI Nord __NEXT_DATA__ payload is missing")
    try:
        next_data = json.loads(html_lib.unescape(match.group(1)).strip())
    except json.JSONDecodeError as exc:
        raise AldiNordDailySpecialError(
            "ALDI Nord __NEXT_DATA__ payload is invalid JSON"
        ) from exc

    page_props = ((next_data.get("props") or {}).get("pageProps") or {})
    api_data = page_props.get("apiData")
    if isinstance(api_data, str):
        try:
            api_data = json.loads(api_data)
        except json.JSONDecodeError as exc:
            raise AldiNordDailySpecialError(
                "ALDI Nord pageProps.apiData is invalid JSON"
            ) from exc
    if not isinstance(api_data, list):
        raise AldiNordDailySpecialError(
            "ALDI Nord pageProps.apiData is not a list"
        )

    responses = [
        row[1].get("res")
        for row in api_data
        if (
            isinstance(row, list)
            and len(row) >= 2
            and row[0] == "OFFER_GET"
            and isinstance(row[1], dict)
            and isinstance(row[1].get("res"), dict)
        )
    ]
    if len(responses) != 1:
        raise AldiNordDailySpecialError(
            "ALDI Nord expected exactly one OFFER_GET response, found "
            f"{len(responses)}"
        )
    return responses[0]


def _daily_date(category: dict[str, Any]) -> date | None:
    short_title = category.get("shortTitle")
    start_value = category.get("startDate")
    end_value = category.get("endDate")
    if not isinstance(short_title, str) or not isinstance(start_value, str):
        return None

    label = _DAILY_LABEL_RE.fullmatch(short_title.strip())
    if label is None:
        if short_title.strip().casefold().startswith("nur"):
            raise AldiNordDailySpecialError(
                "ALDI Nord daily category label is not an exact dated "
                "one-day label"
            )
        return None
    try:
        start = date.fromisoformat(start_value)
        label_date = date(
            start.year,
            int(label.group("month")),
            int(label.group("day")),
        )
    except ValueError as exc:
        raise AldiNordDailySpecialError(
            "ALDI Nord explicit daily label has an invalid date"
        ) from exc
    if label_date != start:
        raise AldiNordDailySpecialError(
            "ALDI Nord explicit daily label does not match category start date"
        )
    if end_value != start_value:
        raise AldiNordDailySpecialError(
            "ALDI Nord explicit daily label does not have a one-day category range"
        )
    return start


def _category_product_ids(category: dict[str, Any]) -> list[str]:
    content = category.get("content")
    if not isinstance(content, list):
        raise AldiNordDailySpecialError(
            "ALDI Nord daily category content is not a list"
        )
    product_ids: list[str] = []
    for row in content:
        if not isinstance(row, dict):
            raise AldiNordDailySpecialError(
                "ALDI Nord daily category content row is not an object"
            )
        values = row.get("productIds")
        if values is None:
            continue
        if not isinstance(values, list):
            raise AldiNordDailySpecialError(
                "ALDI Nord daily category productIds is not a list"
            )
        for value in values:
            product_id = str(value).strip()
            if not product_id:
                raise AldiNordDailySpecialError(
                    "ALDI Nord daily category has a blank product ID"
                )
            product_ids.append(product_id)
    if not product_ids:
        raise AldiNordDailySpecialError(
            "ALDI Nord explicit daily category has no product IDs"
        )
    return product_ids


def _daily_product(
    raw: dict[str, Any],
    *,
    object_id: str,
    special_valid_on: date,
) -> tuple[Decimal, Decimal | None, Decimal | None, str | None] | None:
    if str(raw.get("objectID") or "").strip() != object_id:
        raise AldiNordDailySpecialError(
            "ALDI Nord daily product object ID does not match category reference: "
            f"{object_id}"
        )
    current_price = raw.get("currentPrice")
    if not isinstance(current_price, dict):
        return None
    sale_price = _decimal(current_price.get("priceValue"))
    if sale_price is None or sale_price <= 0:
        return None

    promotion_prices = raw.get("promotionPrices")
    if not isinstance(promotion_prices, list) or len(promotion_prices) != 1:
        return None
    promotion = promotion_prices[0]
    if not isinstance(promotion, dict):
        return None
    if (
        promotion.get("validFromLocalDate") != special_valid_on.isoformat()
        or promotion.get("validUntilLocalDate") != special_valid_on.isoformat()
        or _decimal(promotion.get("priceValue")) != sale_price
    ):
        return None

    unit_price, unit_label = _unit_price(current_price)
    return (
        sale_price,
        _regular_price(current_price, sale_price),
        unit_price,
        unit_label,
    )


def extract_aldi_nord_daily_specials(
    html: bytes | str,
    context: AldiNordDailySpecialContext,
) -> tuple[OfferCandidate, ...]:
    _validate_source_url(context.source_url)
    response = _offer_response(html)
    offer_map = response.get("algoliaDataMap")
    categories = response.get("categories")
    if not isinstance(offer_map, dict) or not isinstance(categories, list):
        raise AldiNordDailySpecialError(
            "ALDI Nord daily source lacks offer objects or categories"
        )

    raw_rows: list[tuple[str, date, dict[str, Any], dict[str, Any]]] = []
    for category in categories:
        if not isinstance(category, dict):
            raise AldiNordDailySpecialError(
                "ALDI Nord category row is not an object"
            )
        special_valid_on = _daily_date(category)
        if special_valid_on is None:
            continue
        for object_id in _category_product_ids(category):
            raw = offer_map.get(object_id)
            if not isinstance(raw, dict):
                raise AldiNordDailySpecialError(
                    "ALDI Nord daily category references a missing product object: "
                    f"{object_id}"
                )
            raw_rows.append((object_id, special_valid_on, category, raw))

    offers: list[OfferCandidate] = []
    seen_semantic_rows: set[tuple[object, ...]] = set()
    for object_id, special_valid_on, category, raw in sorted(
        raw_rows,
        key=lambda row: (row[1], row[0]),
    ):
        product_name = str(raw.get("name") or "").strip()
        package = str(raw.get("salesUnit") or "").strip()
        if not product_name or not package:
            continue
        price_data = _daily_product(
            raw,
            object_id=object_id,
            special_valid_on=special_valid_on,
        )
        if price_data is None:
            continue
        sale_price, regular_price, unit_price, unit_label = price_data
        brand = str(raw.get("brandName") or "").strip() or None
        semantic_key = (
            special_valid_on,
            product_name.casefold(),
            (brand or "").casefold(),
            package.casefold(),
            sale_price,
            regular_price,
            unit_price,
            unit_label,
        )
        if semantic_key in seen_semantic_rows:
            continue
        seen_semantic_rows.add(semantic_key)

        category_title = str(category.get("title") or "").strip()
        short_title = str(category.get("shortTitle") or "").strip()
        category_products = [
            str(row.get("title") or "").strip()
            for row in category.get("content", [])
            if isinstance(row, dict) and row.get("productIds") is not None
        ]
        source_text = " | ".join(
            value for value in (category_title, short_title, *category_products) if value
        )
        source_offer_id = (
            f"aldi_nord:{object_id}:{special_valid_on.isoformat()}"
        )
        offers.append(
            OfferCandidate(
                source_chain=SourceChain.ALDI_NORD,
                source_offer_id=source_offer_id,
                product_name_raw=product_name,
                brand_raw=brand,
                description_raw=(
                    "ALDI Nord official explicitly one-day structured offer"
                ),
                package_text_raw=package,
                price_eur=sale_price,
                regular_price_eur=regular_price,
                unit_price_eur=unit_price,
                unit_label=unit_label,
                pricing_mode="fixed_package",
                discount_percent=None,
                requires_app=False,
                coupon_required=False,
                valid_from=special_valid_on,
                valid_until=special_valid_on,
                source_url=context.source_url,
                source_image_url=_first_http_url(raw.get("assets")),
                snapshot_id=context.snapshot_id,
                collected_at=context.collected_at,
                parser_version=_PARSER_VERSION,
                raw_payload={
                    "is_daily_special": True,
                    "special_valid_on": special_valid_on.isoformat(),
                    "special_type": "aldi_nord_explicit_daily_category",
                    "special_source_text": source_text,
                    "special_source_kind": (
                        "aldi_nord_next_data_category_and_offer_object"
                    ),
                    "special_source_page": 0,
                    "special_confidence": "high",
                    "source_snapshot_binding": True,
                    "source_snapshot_id": str(context.snapshot_id),
                    "source_snapshot_sha256": context.snapshot_sha256,
                    "source_payload_sha256": context.snapshot_sha256,
                    "source_object_id": object_id,
                    "source_category_title": category_title,
                    "source_category_short_title": short_title,
                    "source_category_valid_from": category["startDate"],
                    "source_category_valid_until": category["endDate"],
                    "source_text_excerpt": source_text,
                    "source_geometry": [],
                    "bundle_quantity": None,
                    "single_price_eur": None,
                    "shadow_only": True,
                    "db_write_eligible": False,
                },
            )
        )
    if raw_rows and not offers:
        raise AldiNordDailySpecialError(
            "ALDI Nord explicit daily category has no complete product evidence"
        )
    return tuple(offers)


@lru_cache(maxsize=8)
def cached_aldi_nord_daily_specials(
    snapshot_id: str,
    snapshot_path: str,
    snapshot_sha256: str,
    source_url: str,
    final_url: str,
    collected_at: str,
) -> tuple[OfferCandidate, ...]:
    path = _verify_file(snapshot_path, snapshot_sha256)
    try:
        parsed_snapshot_id = UUID(snapshot_id)
        parsed_collected_at = datetime.fromisoformat(collected_at)
    except ValueError as exc:
        raise AldiNordDailySpecialError(
            "ALDI Nord snapshot metadata is invalid"
        ) from exc
    return extract_aldi_nord_daily_specials(
        path.read_bytes(),
        AldiNordDailySpecialContext(
            snapshot_id=parsed_snapshot_id,
            snapshot_sha256=snapshot_sha256,
            source_url=final_url or source_url,
            collected_at=parsed_collected_at,
        ),
    )
