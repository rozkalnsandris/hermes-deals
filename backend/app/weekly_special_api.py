from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any
from uuid import UUID
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.aldi_nord_daily_special import (
    AldiNordDailySpecialError,
    cached_aldi_nord_daily_specials,
)
from app.branding_overlay_api import router as branding_router
from app.completeness_rescue_read import (
    dedupe_completeness_rescue_publications,
)
from app.db import get_db
from app.models import OfferCandidateRecord, SourceSnapshot
from app.netto_daily_special_api import (
    _assert_read_only_session,
    _cached_snapshot_offers,
    _snapshot_manifest_window,
    _to_output,
)
from app.weekly_retailer_state import build_weekly_retailer_states


router = APIRouter()
router.include_router(branding_router)
_TIMEZONE = "Europe/Berlin"
_WEEK_DAYS = 7
_SPECIAL_MAX_DAYS = 3
_CACHE_TTL_SECONDS = 30.0
_CACHE_LIMIT = 8
_SOURCE_CONTRACT = (
    "single_week_query_short_periods_plus_explicit_immutable_daily_evidence"
)
_UI_CONTRACT = "normalized_unique_deals_by_id_v1"
_UI_BRIDGE_PATH = (
    Path(__file__).resolve().parent / "ui" / "weekly-payload-bridge.js"
)


class WeeklyDealOut(BaseModel):
    offer_candidate_id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str
    product_name_raw: str
    brand_raw: str | None
    package_text_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    pricing_mode: str | None = None
    regular_unit_price_eur: Decimal | None = None
    example_weight_g: Decimal | None = None
    discount_percent: Decimal | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date | None
    valid_until: date | None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    base_price_current: bool
    app_price_current: bool
    source_url: str | None
    source_image_url: str | None
    collected_at: datetime
    canonical_product_id: UUID | None = None
    canonical_comparable: bool = False
    is_daily_special: bool = False
    special_valid_on: date | None = None
    special_type: str | None = None
    special_source_text: str | None = None
    special_source_kind: str | None = None
    special_source_page: int | None = None
    special_confidence: str | None = None
    bundle_quantity: int | None = None
    single_price_eur: Decimal | None = None
    deposit_eur: Decimal | None = None
    shadow_only: bool = False
    source_snapshot_id: UUID | None = None
    source_snapshot_sha256: str | None = None


class WeeklyDayOut(BaseModel):
    date: date
    deals: list[WeeklyDealOut]


class WeeklyRetailerStateOut(BaseModel):
    retailer_key: str
    display_name: str
    source_chain: str
    state: str
    reason: str
    deal_count: int
    active_dates: list[date]
    last_verified_at: datetime | None = None
    last_verified_campaign: str | None = None
    last_verified_evidence_sha256: str | None = None
    last_verified_valid_from: date | None = None
    last_verified_valid_until: date | None = None


class WeeklySpecialsOut(BaseModel):
    week_start: date
    week_end: date
    timezone: str
    count: int
    source_contract: str
    retailers: list[WeeklyRetailerStateOut] = Field(default_factory=list)
    days: list[WeeklyDayOut]


class WeeklyUiDealOut(BaseModel):
    offer_candidate_id: UUID
    source_chain: str
    source_store_name: str | None = None
    product_name_raw: str
    brand_raw: str | None = None
    package_text_raw: str | None = None
    price_eur: Decimal
    regular_price_eur: Decimal | None = None
    unit_price_eur: Decimal | None = None
    unit_label: str | None = None
    pricing_mode: str | None = None
    discount_percent: Decimal | None = None
    app_price_eur: Decimal | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    app_valid_from: date | None = None
    app_valid_until: date | None = None
    source_url: str | None = None
    source_image_url: str | None = None
    canonical_product_id: UUID | None = None
    canonical_comparable: bool = False
    is_daily_special: bool = False
    special_valid_on: date | None = None
    special_confidence: str | None = None
    deposit_eur: Decimal | None = None


class WeeklyUiDayOut(BaseModel):
    date: date
    deal_ids: list[UUID]


class WeeklyUiSpecialsOut(BaseModel):
    week_start: date
    week_end: date
    timezone: str
    count: int
    source_contract: str
    ui_contract: str
    retailers: list[WeeklyRetailerStateOut] = Field(default_factory=list)
    deals: list[WeeklyUiDealOut]
    days: list[WeeklyUiDayOut]


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    body: bytes
    etag: str


_CACHE: OrderedDict[date, _CacheEntry] = OrderedDict()
_UI_CACHE: OrderedDict[date, _CacheEntry] = OrderedDict()


def _clear_weekly_cache() -> None:
    _CACHE.clear()
    _UI_CACHE.clear()


def _week_dates(week_start: date) -> tuple[date, ...]:
    return tuple(
        week_start + timedelta(days=offset)
        for offset in range(_WEEK_DAYS)
    )


def _qualifying_windows(
    row: OfferCandidateRecord,
) -> tuple[tuple[date, date, str], ...]:
    windows: list[tuple[date, date, str]] = []

    def add(start: date | None, end: date | None, kind: str) -> None:
        if start is None or end is None or start > end:
            return
        span = (end - start).days + 1
        if span <= _SPECIAL_MAX_DAYS:
            windows.append((start, end, kind))

    if row.source_chain == "netto":
        return ()
    add(row.valid_from, row.valid_until, "base")
    if row.app_price_eur is not None:
        add(row.app_valid_from, row.app_valid_until, "app")
    return tuple(windows)


def _query_week_rows(
    db: Session,
    week_start: date,
    week_end: date,
) -> list[OfferCandidateRecord]:
    overlap = or_(
        and_(
            OfferCandidateRecord.valid_from.is_not(None),
            OfferCandidateRecord.valid_until.is_not(None),
            OfferCandidateRecord.valid_from <= week_end,
            OfferCandidateRecord.valid_until >= week_start,
        ),
        and_(
            OfferCandidateRecord.app_price_eur.is_not(None),
            OfferCandidateRecord.app_valid_from.is_not(None),
            OfferCandidateRecord.app_valid_until.is_not(None),
            OfferCandidateRecord.app_valid_from <= week_end,
            OfferCandidateRecord.app_valid_until >= week_start,
        ),
    )
    return list(
        db.scalars(
            select(OfferCandidateRecord).where(
                OfferCandidateRecord.source_offer_id.is_not(None),
                OfferCandidateRecord.source_chain != "netto",
                overlap,
            )
        ).all()
    )


def _ordinary_output(
    row: OfferCandidateRecord,
    active_on: date,
) -> WeeklyDealOut:
    return WeeklyDealOut(
        offer_candidate_id=row.id,
        source_chain=row.source_chain,
        source_store_external_id=row.source_store_external_id,
        source_store_name=row.source_store_name,
        source_offer_id=row.source_offer_id or "",
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
        base_price_current=bool(
            row.valid_from is not None
            and row.valid_until is not None
            and row.valid_from <= active_on <= row.valid_until
        ),
        app_price_current=bool(
            row.app_price_eur is not None
            and row.app_valid_from is not None
            and row.app_valid_until is not None
            and row.app_valid_from <= active_on <= row.app_valid_until
        ),
        source_url=row.source_url,
        source_image_url=row.source_image_url,
        collected_at=row.collected_at,
    )


def _ordinary_days(
    rows: list[OfferCandidateRecord],
    week_start: date,
) -> dict[date, list[WeeklyDealOut]]:
    result = {day: [] for day in _week_dates(week_start)}
    for day in result:
        newest: dict[
            tuple[str, str | None, str],
            OfferCandidateRecord,
        ] = {}
        for row in rows:
            if row.source_offer_id is None:
                continue
            windows = _qualifying_windows(row)
            if not any(start <= day <= end for start, end, _ in windows):
                continue
            key = (
                row.source_chain,
                row.source_store_external_id,
                row.source_offer_id,
            )
            existing = newest.get(key)
            if existing is None or (
                row.collected_at,
                str(row.id),
            ) > (
                existing.collected_at,
                str(existing.id),
            ):
                newest[key] = row

        visible = dedupe_completeness_rescue_publications(
            ("current", row)
            for row in newest.values()
        )
        result[day] = [
            _ordinary_output(row, day)
            for _, row in visible
        ]
    return result


def _snapshot_rows(db: Session) -> list[SourceSnapshot]:
    return list(
        db.scalars(
            select(SourceSnapshot)
            .where(
                SourceSnapshot.success.is_(True),
                or_(
                    and_(
                        SourceSnapshot.source_chain == "netto",
                        SourceSnapshot.scope == "family_primary_netto",
                    ),
                    and_(
                        SourceSnapshot.source_chain == "aldi_nord",
                        SourceSnapshot.scope == "national_offers",
                    ),
                ),
            )
            .order_by(
                SourceSnapshot.source_chain.asc(),
                SourceSnapshot.collected_at.desc(),
            )
        ).all()
    )


def _explicit_daily_specials(
    db: Session,
    week_start: date,
    week_end: date,
) -> dict[date, list[WeeklyDealOut]]:
    result = {day: [] for day in _week_dates(week_start)}
    snapshots = _snapshot_rows(db)
    netto_snapshots = [
        snapshot
        for snapshot in snapshots
        if snapshot.source_chain == "netto"
    ]
    if not netto_snapshots:
        raise HTTPException(
            status_code=503,
            detail="Immutable Netto snapshots are unavailable",
        )

    offers_by_key: dict[
        tuple[str, str, date],
        Any,
    ] = {}

    for snapshot in netto_snapshots:
        valid_from, valid_until = _snapshot_manifest_window(snapshot)
        if valid_until < week_start or valid_from > week_end:
            continue
        try:
            offers = _cached_snapshot_offers(
                str(snapshot.id),
                snapshot.snapshot_path or "",
                snapshot.sha256 or "",
                snapshot.source_url,
                snapshot.final_url or "",
                snapshot.collected_at.isoformat(),
            )
        except RuntimeError as exc:
            if str(exc) == "Netto prospect PDF path is missing":
                offers = ()
            else:
                raise HTTPException(
                    status_code=503,
                    detail=f"Netto daily-special evidence unavailable: {exc}",
                ) from exc
        except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Netto daily-special evidence unavailable: {exc}",
            ) from exc
        for offer in offers:
            raw = offer.raw_payload
            if (
                raw.get("is_daily_special") is not True
                or raw.get("special_confidence") != "high"
            ):
                continue
            try:
                valid_on = date.fromisoformat(
                    str(raw.get("special_valid_on") or "")
                )
            except ValueError:
                continue
            if not week_start <= valid_on <= week_end:
                continue
            key = (
                offer.source_chain.value,
                offer.source_offer_id or "",
                valid_on,
            )
            existing = offers_by_key.get(key)
            if existing is None or offer.collected_at > existing.collected_at:
                offers_by_key[key] = offer

    aldi_snapshot = next(
        (
            snapshot
            for snapshot in snapshots
            if snapshot.source_chain == "aldi_nord"
        ),
        None,
    )
    if aldi_snapshot is not None:
        if not aldi_snapshot.snapshot_path or not aldi_snapshot.sha256:
            raise HTTPException(
                status_code=503,
                detail="Latest immutable ALDI Nord snapshot is unavailable",
            )
        try:
            aldi_offers = cached_aldi_nord_daily_specials(
                str(aldi_snapshot.id),
                aldi_snapshot.snapshot_path,
                aldi_snapshot.sha256,
                aldi_snapshot.source_url,
                aldi_snapshot.final_url or "",
                aldi_snapshot.collected_at.isoformat(),
            )
        except AldiNordDailySpecialError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "ALDI Nord daily-special evidence unavailable: "
                    f"{exc}"
                ),
            ) from exc
        except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "ALDI Nord daily-special evidence unavailable: "
                    f"{exc}"
                ),
            ) from exc
        for offer in aldi_offers:
            raw = offer.raw_payload
            if (
                raw.get("is_daily_special") is not True
                or raw.get("special_confidence") != "high"
            ):
                continue
            try:
                valid_on = date.fromisoformat(
                    str(raw.get("special_valid_on") or "")
                )
            except ValueError:
                continue
            if not week_start <= valid_on <= week_end:
                continue
            key = (
                offer.source_chain.value,
                offer.source_offer_id or "",
                valid_on,
            )
            existing = offers_by_key.get(key)
            if existing is None or offer.collected_at > existing.collected_at:
                offers_by_key[key] = offer

    for (_, _, valid_on), offer in offers_by_key.items():
        result[valid_on].append(
            WeeklyDealOut.model_validate(
                _to_output(offer, valid_on).model_dump()
            )
        )
    return result


def _merge_days(
    ordinary: dict[date, list[WeeklyDealOut]],
    explicit: dict[date, list[WeeklyDealOut]],
    week_start: date,
) -> list[WeeklyDayOut]:
    days: list[WeeklyDayOut] = []
    for day in _week_dates(week_start):
        seen: set[UUID] = set()
        merged: list[WeeklyDealOut] = []
        for deal in (*explicit.get(day, []), *ordinary.get(day, [])):
            if deal.offer_candidate_id in seen:
                continue
            seen.add(deal.offer_candidate_id)
            merged.append(deal)
        merged.sort(
            key=lambda row: (
                row.source_chain,
                row.product_name_raw.casefold(),
                row.price_eur,
                row.source_offer_id,
            )
        )
        days.append(WeeklyDayOut(date=day, deals=merged))
    return days


def _build_payload(
    db: Session,
    week_start: date,
) -> WeeklySpecialsOut:
    week_end = week_start + timedelta(days=_WEEK_DAYS - 1)
    rows = _query_week_rows(db, week_start, week_end)
    ordinary = _ordinary_days(rows, week_start)
    explicit = _explicit_daily_specials(db, week_start, week_end)
    days = _merge_days(ordinary, explicit, week_start)
    retailers = [
        WeeklyRetailerStateOut.model_validate(row)
        for row in build_weekly_retailer_states(
            db,
            days,
            week_start,
            week_end,
        )
    ]
    return WeeklySpecialsOut(
        week_start=week_start,
        week_end=week_end,
        timezone=_TIMEZONE,
        count=sum(len(day.deals) for day in days),
        source_contract=_SOURCE_CONTRACT,
        retailers=retailers,
        days=days,
    )


def _normalize_ui_payload(payload: WeeklySpecialsOut) -> WeeklyUiSpecialsOut:
    unique: OrderedDict[UUID, WeeklyUiDealOut] = OrderedDict()
    days: list[WeeklyUiDayOut] = []
    for day in payload.days:
        deal_ids: list[UUID] = []
        for deal in day.deals:
            normalized = WeeklyUiDealOut.model_validate(deal.model_dump())
            existing = unique.get(deal.offer_candidate_id)
            if existing is None:
                unique[deal.offer_candidate_id] = normalized
            elif existing != normalized:
                raise RuntimeError(
                    "Weekly UI normalization conflict for offer_candidate_id"
                )
            deal_ids.append(deal.offer_candidate_id)
        days.append(WeeklyUiDayOut(date=day.date, deal_ids=deal_ids))

    if payload.count != sum(len(day.deal_ids) for day in days):
        raise RuntimeError("Weekly UI normalization changed the day-entry count")

    return WeeklyUiSpecialsOut(
        week_start=payload.week_start,
        week_end=payload.week_end,
        timezone=payload.timezone,
        count=payload.count,
        source_contract=payload.source_contract,
        ui_contract=_UI_CONTRACT,
        retailers=payload.retailers,
        deals=list(unique.values()),
        days=days,
    )


def _ui_payload_body(payload: WeeklySpecialsOut) -> bytes:
    return _normalize_ui_payload(payload).model_dump_json(
        exclude_none=True
    ).encode("utf-8")


def _cache_headers(
    etag: str,
    elapsed_ms: float,
    cache_state: str,
) -> dict[str, str]:
    return {
        "Cache-Control": (
            "private, max-age=30, stale-while-revalidate=300"
        ),
        "ETag": etag,
        "Vary": "Accept-Encoding",
        "Server-Timing": f"weekly;dur={elapsed_ms:.1f}",
        "X-Hermes-Weekly-Cache": cache_state,
    }


def _etag_matches(request: Request, etag: str) -> bool:
    raw = request.headers.get("if-none-match", "")
    return any(
        candidate.strip() in {etag, "*"}
        for candidate in raw.split(",")
        if candidate.strip()
    )


def _cached_weekly_response(
    *,
    request: Request,
    cache: OrderedDict[date, _CacheEntry],
    week_start: date,
    started: float,
) -> Response | None:
    cached = cache.get(week_start)
    if cached is None or cached.expires_at <= monotonic():
        return None
    cache.move_to_end(week_start)
    elapsed_ms = (perf_counter() - started) * 1000
    headers = _cache_headers(cached.etag, elapsed_ms, "HIT")
    if _etag_matches(request, cached.etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=cached.body,
        media_type="application/json",
        headers=headers,
    )


def _store_weekly_response(
    *,
    cache: OrderedDict[date, _CacheEntry],
    week_start: date,
    body: bytes,
) -> str:
    etag = f'"{sha256(body).hexdigest()}"'
    cache[week_start] = _CacheEntry(
        expires_at=monotonic() + _CACHE_TTL_SECONDS,
        body=body,
        etag=etag,
    )
    cache.move_to_end(week_start)
    while len(cache) > _CACHE_LIMIT:
        cache.popitem(last=False)
    return etag


@router.get("/ui/weekly-payload-bridge.js", include_in_schema=False)
def weekly_payload_bridge() -> FileResponse:
    if not _UI_BRIDGE_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Weekly UI payload bridge is not available",
        )
    return FileResponse(_UI_BRIDGE_PATH, media_type="application/javascript")


@router.get(
    "/api/v1/deals/weekly-specials",
    response_model=WeeklySpecialsOut,
    responses={304: {"description": "Weekly data is unchanged"}},
)
def weekly_specials(
    request: Request,
    week_start: date = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    if week_start.isoweekday() != 1:
        raise HTTPException(
            status_code=422,
            detail="week_start must be a Monday",
        )

    started = perf_counter()
    cached_response = _cached_weekly_response(
        request=request,
        cache=_CACHE,
        week_start=week_start,
        started=started,
    )
    if cached_response is not None:
        return cached_response

    _assert_read_only_session(db)
    payload = _build_payload(db, week_start)
    ui_body = _ui_payload_body(payload)
    _store_weekly_response(
        cache=_UI_CACHE,
        week_start=week_start,
        body=ui_body,
    )
    body = payload.model_dump_json().encode("utf-8")
    etag = _store_weekly_response(
        cache=_CACHE,
        week_start=week_start,
        body=body,
    )

    elapsed_ms = (perf_counter() - started) * 1000
    headers = _cache_headers(etag, elapsed_ms, "MISS")
    if _etag_matches(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=body,
        media_type="application/json",
        headers=headers,
    )


@router.get(
    "/api/v1/deals/weekly-specials/ui",
    response_model=WeeklyUiSpecialsOut,
    responses={304: {"description": "Weekly UI data is unchanged"}},
)
def weekly_specials_ui(
    request: Request,
    week_start: date = Query(...),
    db: Session = Depends(get_db),
) -> Response:
    if week_start.isoweekday() != 1:
        raise HTTPException(
            status_code=422,
            detail="week_start must be a Monday",
        )

    started = perf_counter()
    cached_response = _cached_weekly_response(
        request=request,
        cache=_UI_CACHE,
        week_start=week_start,
        started=started,
    )
    if cached_response is not None:
        return cached_response

    _assert_read_only_session(db)
    body = _ui_payload_body(_build_payload(db, week_start))
    etag = _store_weekly_response(
        cache=_UI_CACHE,
        week_start=week_start,
        body=body,
    )

    elapsed_ms = (perf_counter() - started) * 1000
    headers = _cache_headers(etag, elapsed_ms, "MISS")
    if _etag_matches(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=body,
        media_type="application/json",
        headers=headers,
    )