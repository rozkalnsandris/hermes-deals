from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from time import monotonic
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.completeness_rescue_read import (
    dedupe_completeness_rescue_publications,
)
from app.db import get_db
from app.models import OfferCandidateRecord, OfferProductLink
from app.schemas import CurrentDealOut, CurrentDealsOut, SourceChain
from app.weekly_special_api import router


_CACHE_TTL_SECONDS = 15.0
_CACHE_LIMIT = 64
_UNIT_BASIS_PRICING_MODES = {
    "unit_price_only",
    "example_total_plus_unit",
    "app_example_total_plus_unit",
}


@dataclass(frozen=True)
class _OfferMeta:
    id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_offer_id: str
    collected_at: datetime
    valid_from: date | None
    valid_until: date | None
    app_price_eur: Decimal | None
    app_valid_from: date | None
    app_valid_until: date | None


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    payload: CurrentDealsOut


_CACHE: OrderedDict[tuple[object, ...], _CacheEntry] = OrderedDict()


def _clear_current_deals_cache() -> None:
    _CACHE.clear()


def _price_windows(row: _OfferMeta) -> tuple[tuple[date, date], ...]:
    windows: list[tuple[date, date]] = []
    if row.valid_from is not None and row.valid_until is not None:
        windows.append((row.valid_from, row.valid_until))
    if (
        row.app_price_eur is not None
        and row.app_valid_from is not None
        and row.app_valid_until is not None
    ):
        windows.append((row.app_valid_from, row.app_valid_until))
    return tuple(windows)


def _availability_state(
    row: _OfferMeta,
    effective_date: date,
) -> Literal["current", "upcoming", "expired", "unknown"]:
    windows = _price_windows(row)
    if any(start <= effective_date <= end for start, end in windows):
        return "current"
    if any(start > effective_date for start, _ in windows):
        return "upcoming"
    if windows and all(end < effective_date for _, end in windows):
        return "expired"
    return "unknown"


def _load_newest_state_rows(
    db: Session,
    effective_date: date,
) -> list[tuple[str, OfferCandidateRecord]]:
    metadata_rows = db.execute(
        select(
            OfferCandidateRecord.id,
            OfferCandidateRecord.source_chain,
            OfferCandidateRecord.source_store_external_id,
            OfferCandidateRecord.source_offer_id,
            OfferCandidateRecord.collected_at,
            OfferCandidateRecord.valid_from,
            OfferCandidateRecord.valid_until,
            OfferCandidateRecord.app_price_eur,
            OfferCandidateRecord.app_valid_from,
            OfferCandidateRecord.app_valid_until,
        ).where(OfferCandidateRecord.source_offer_id.is_not(None))
    ).all()

    newest: dict[
        tuple[str, str, str | None, str],
        _OfferMeta,
    ] = {}
    for raw in metadata_rows:
        if raw.source_offer_id is None:
            continue
        meta = _OfferMeta(
            id=raw.id,
            source_chain=raw.source_chain,
            source_store_external_id=raw.source_store_external_id,
            source_offer_id=raw.source_offer_id,
            collected_at=raw.collected_at,
            valid_from=raw.valid_from,
            valid_until=raw.valid_until,
            app_price_eur=raw.app_price_eur,
            app_valid_from=raw.app_valid_from,
            app_valid_until=raw.app_valid_until,
        )
        state = _availability_state(meta, effective_date)
        key = (
            state,
            meta.source_chain,
            meta.source_store_external_id,
            meta.source_offer_id,
        )
        existing = newest.get(key)
        if existing is None or (
            meta.collected_at,
            str(meta.id),
        ) > (
            existing.collected_at,
            str(existing.id),
        ):
            newest[key] = meta

    if not newest:
        return []

    full_rows = list(
        db.scalars(
            select(OfferCandidateRecord).where(
                OfferCandidateRecord.id.in_(
                    [meta.id for meta in newest.values()]
                )
            )
        ).all()
    )
    full_by_id = {row.id: row for row in full_rows}
    state_rows = [
        (key[0], full_by_id[meta.id])
        for key, meta in newest.items()
        if meta.id in full_by_id
    ]
    return dedupe_completeness_rescue_publications(state_rows)


def _has_app(row: OfferCandidateRecord) -> bool:
    return row.app_price_eur is not None or row.requires_app


def _has_discount(row: OfferCandidateRecord) -> bool:
    return bool(
        (
            row.regular_price_eur is not None
            and row.regular_price_eur > row.price_eur
        )
        or (
            row.discount_percent is not None
            and row.discount_percent > 0
        )
    )


def _saving(row: OfferCandidateRecord) -> Decimal:
    if (
        row.regular_price_eur is not None
        and row.regular_price_eur > row.price_eur
    ):
        return row.regular_price_eur - row.price_eur
    return Decimal("0")


def _cache_key(
    effective_date: date,
    q: str | None,
    retailer: str | None,
    view: str,
    app_only: bool,
    coupon_only: bool,
    discount_only: bool,
    image_only: bool,
    sort: str,
    offset: int,
    limit: int,
) -> tuple[object, ...]:
    return (
        effective_date,
        q,
        retailer,
        view,
        app_only,
        coupon_only,
        discount_only,
        image_only,
        sort,
        offset,
        limit,
    )


def _remember(key: tuple[object, ...], payload: CurrentDealsOut) -> None:
    _CACHE[key] = _CacheEntry(
        expires_at=monotonic() + _CACHE_TTL_SECONDS,
        payload=payload,
    )
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)


@router.get(
    "/api/v1/deals/current",
    response_model=CurrentDealsOut,
    include_in_schema=False,
)
def fast_current_deals(
    as_of: date | None = Query(default=None),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    retailer: str | None = Query(default=None, max_length=32),
    view: str = Query(default="current", pattern="^(current|upcoming)$"),
    app_only: bool = Query(default=False),
    coupon_only: bool = Query(default=False),
    discount_only: bool = Query(default=False),
    image_only: bool = Query(default=False),
    sort: str = Query(
        default="name",
        pattern="^(name|price_asc|price_desc|newest|discount_desc)$",
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=500),
    db: Session = Depends(get_db),
) -> CurrentDealsOut:
    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )
    key = _cache_key(
        effective_date,
        q,
        retailer,
        view,
        app_only,
        coupon_only,
        discount_only,
        image_only,
        sort,
        offset,
        limit,
    )
    cached = _CACHE.get(key)
    now = monotonic()
    if cached is not None and cached.expires_at > now:
        _CACHE.move_to_end(key)
        return cached.payload
    if cached is not None:
        _CACHE.pop(key, None)

    visible_state_rows = _load_newest_state_rows(db, effective_date)

    availability_counts = {
        "current": 0,
        "upcoming": 0,
        "unknown": 0,
        "expired": 0,
    }
    retailer_availability: dict[str, dict[str, int]] = {
        chain.value: {
            "current": 0,
            "upcoming": 0,
            "unknown": 0,
            "expired": 0,
        }
        for chain in SourceChain
    }

    current_rows: list[OfferCandidateRecord] = []
    for state, row in visible_state_rows:
        availability_counts[state] += 1
        retailer_availability[row.source_chain][state] += 1
        if state == view:
            current_rows.append(row)

    normalized_query = q.strip().casefold() if q is not None else None
    if normalized_query:
        current_rows = [
            row
            for row in current_rows
            if normalized_query in row.product_name_raw.casefold()
            or (
                row.brand_raw is not None
                and normalized_query in row.brand_raw.casefold()
            )
            or (
                row.description_raw is not None
                and normalized_query in row.description_raw.casefold()
            )
            or (
                row.package_text_raw is not None
                and normalized_query in row.package_text_raw.casefold()
            )
        ]

    retailer_counts: dict[str, int] = {}
    for row in current_rows:
        retailer_counts[row.source_chain] = (
            retailer_counts.get(row.source_chain, 0) + 1
        )

    feature_counts = {
        "app": sum(1 for row in current_rows if _has_app(row)),
        "coupon": sum(1 for row in current_rows if row.coupon_required),
        "discount": sum(1 for row in current_rows if _has_discount(row)),
        "image": sum(1 for row in current_rows if row.source_image_url),
        "canonical": 0,
    }

    if retailer:
        retailer_key = retailer.strip().casefold()
        current_rows = [
            row
            for row in current_rows
            if row.source_chain.casefold() == retailer_key
        ]
    if app_only:
        current_rows = [row for row in current_rows if _has_app(row)]
    if coupon_only:
        current_rows = [row for row in current_rows if row.coupon_required]
    if discount_only:
        current_rows = [row for row in current_rows if _has_discount(row)]
    if image_only:
        current_rows = [row for row in current_rows if row.source_image_url]

    if sort == "price_asc":
        current_rows.sort(
            key=lambda row: (
                row.price_eur,
                row.product_name_raw.casefold(),
                row.source_chain,
            )
        )
    elif sort == "price_desc":
        current_rows.sort(
            key=lambda row: (
                -row.price_eur,
                row.product_name_raw.casefold(),
                row.source_chain,
            )
        )
    elif sort == "newest":
        current_rows.sort(
            key=lambda row: (
                -row.collected_at.timestamp(),
                row.product_name_raw.casefold(),
                row.source_chain,
            )
        )
    elif sort == "discount_desc":
        current_rows.sort(
            key=lambda row: (
                -_saving(row),
                -(row.discount_percent or Decimal("0")),
                row.price_eur,
                row.product_name_raw.casefold(),
            )
        )
    else:
        current_rows.sort(
            key=lambda row: (
                row.product_name_raw.casefold(),
                (row.brand_raw or "").casefold(),
                row.price_eur,
                row.source_chain,
                row.source_store_external_id or "",
                row.source_offer_id or "",
            )
        )

    available_count = len(current_rows)
    selected_rows = current_rows[offset : offset + limit]

    identity_keys = {
        (
            row.source_chain,
            row.source_store_external_id,
            row.source_offer_id,
        )
        for row in current_rows
        if row.source_offer_id is not None
    }
    canonical_ids_by_identity: dict[
        tuple[str, str | None, str],
        set[UUID],
    ] = {}
    if identity_keys:
        source_offer_ids = {key[2] for key in identity_keys}
        linked_identity_rows = db.execute(
            select(
                OfferCandidateRecord.source_chain,
                OfferCandidateRecord.source_store_external_id,
                OfferCandidateRecord.source_offer_id,
                OfferProductLink.canonical_product_id,
            )
            .join(
                OfferProductLink,
                OfferProductLink.offer_candidate_id
                == OfferCandidateRecord.id,
            )
            .where(
                OfferCandidateRecord.source_offer_id.in_(source_offer_ids)
            )
        ).all()
        for (
            source_chain,
            source_store_external_id,
            source_offer_id,
            canonical_product_id,
        ) in linked_identity_rows:
            if source_offer_id is None:
                continue
            identity = (
                source_chain,
                source_store_external_id,
                source_offer_id,
            )
            if identity in identity_keys:
                canonical_ids_by_identity.setdefault(identity, set()).add(
                    canonical_product_id
                )

    canonical_by_identity = {
        identity: next(iter(canonical_ids))
        for identity, canonical_ids in canonical_ids_by_identity.items()
        if len(canonical_ids) == 1
    }
    link_map: dict[UUID, UUID] = {}
    for row in current_rows:
        if row.source_offer_id is None:
            continue
        identity = (
            row.source_chain,
            row.source_store_external_id,
            row.source_offer_id,
        )
        canonical_product_id = canonical_by_identity.get(identity)
        if canonical_product_id is not None:
            link_map[row.id] = canonical_product_id

    feature_counts["canonical"] = len(link_map)

    deals = [
        CurrentDealOut(
            offer_candidate_id=row.id,
            source_chain=row.source_chain,
            source_store_external_id=row.source_store_external_id,
            source_store_name=row.source_store_name,
            source_offer_id=row.source_offer_id,
            product_name_raw=row.product_name_raw,
            brand_raw=row.brand_raw,
            package_text_raw=row.package_text_raw,
            price_eur=row.price_eur,
            regular_price_eur=row.regular_price_eur,
            unit_price_eur=row.unit_price_eur,
            unit_label=row.unit_label,
            pricing_mode=row.pricing_mode,
            regular_unit_price_eur=row.regular_unit_price_eur,
            example_weight_g=row.example_weight_g,
            discount_percent=row.discount_percent,
            app_price_eur=row.app_price_eur,
            requires_app=row.requires_app,
            coupon_required=row.coupon_required,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            app_valid_from=row.app_valid_from,
            app_valid_until=row.app_valid_until,
            source_url=row.source_url,
            source_image_url=row.source_image_url,
            collected_at=row.collected_at,
            base_price_current=(
                row.valid_from is not None
                and row.valid_until is not None
                and row.valid_from <= effective_date <= row.valid_until
            ),
            app_price_current=(
                row.app_price_eur is not None
                and row.app_valid_from is not None
                and row.app_valid_until is not None
                and row.app_valid_from <= effective_date <= row.app_valid_until
            ),
            canonical_product_id=link_map.get(row.id),
            canonical_comparable=(
                row.id in link_map
                and row.pricing_mode not in _UNIT_BASIS_PRICING_MODES
            ),
        )
        for row in selected_rows
    ]

    payload = CurrentDealsOut(
        as_of=effective_date,
        timezone="Europe/Berlin",
        query=q,
        retailer=retailer,
        app_only=app_only,
        coupon_only=coupon_only,
        discount_only=discount_only,
        image_only=image_only,
        available_count=available_count,
        offset=offset,
        limit=limit,
        count=len(deals),
        retailer_counts=retailer_counts,
        feature_counts=feature_counts,
        availability_counts=availability_counts,
        retailer_availability=retailer_availability,
        deals=deals,
    )
    _remember(key, payload)
    return payload
