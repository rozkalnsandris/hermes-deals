from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from time import monotonic, perf_counter
from typing import Iterator
from zoneinfo import ZoneInfo

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.current_deals_service import (
    StateRowLoader,
    _OfferMeta,
    _availability_state,
    build_current_deals,
    load_python_ranked_state_rows,
)
from app.db import get_db
from app.schemas import CurrentDealsOut
from app.weekly_special_api import router


_CACHE_TTL_SECONDS = 15.0
_CACHE_LIMIT = 64
_CURRENT_DEALS_TIMINGS: ContextVar[dict[str, object] | None] = ContextVar(
    "hermes_current_deals_timings",
    default=None,
)


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    payload: CurrentDealsOut


_CACHE: OrderedDict[tuple[object, ...], _CacheEntry] = OrderedDict()
_load_newest_state_rows = load_python_ranked_state_rows


@contextmanager
def capture_current_deals_timings() -> Iterator[dict[str, object]]:
    """Capture request-local backend stage timings for Server-Timing."""

    timings: dict[str, object] = {}
    token = _CURRENT_DEALS_TIMINGS.set(timings)
    try:
        yield timings
    finally:
        _CURRENT_DEALS_TIMINGS.reset(token)


def _record_stage(name: str, started: float) -> None:
    timings = _CURRENT_DEALS_TIMINGS.get()
    if timings is not None:
        timings[name] = (perf_counter() - started) * 1000


def _record_cache_state(state: str) -> None:
    timings = _CURRENT_DEALS_TIMINGS.get()
    if timings is not None:
        timings["cache_state"] = state


def _clear_current_deals_cache() -> None:
    _CACHE.clear()


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


def cached_current_deals(
    *,
    as_of: date | None,
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
    db: Session,
    state_row_loader: StateRowLoader,
) -> CurrentDealsOut:
    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )
    key = _cache_key(
        effective_date, q, retailer, view, app_only, coupon_only,
        discount_only, image_only, sort, offset, limit,
    )

    cache_started = perf_counter()
    cached = _CACHE.get(key)
    now = monotonic()
    if cached is not None and cached.expires_at > now:
        _CACHE.move_to_end(key)
        _record_cache_state("hit")
        _record_stage("cache", cache_started)
        return cached.payload
    if cached is not None:
        _CACHE.pop(key, None)
    _record_cache_state("miss")
    _record_stage("cache", cache_started)

    payload = build_current_deals(
        db=db,
        effective_date=effective_date,
        q=q,
        retailer=retailer,
        view=view,
        app_only=app_only,
        coupon_only=coupon_only,
        discount_only=discount_only,
        image_only=image_only,
        sort=sort,
        offset=offset,
        limit=limit,
        state_row_loader=state_row_loader,
        record_stage=_record_stage,
    )
    _remember(key, payload)
    return payload


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
    return cached_current_deals(
        as_of=as_of,
        q=q,
        retailer=retailer,
        view=view,
        app_only=app_only,
        coupon_only=coupon_only,
        discount_only=discount_only,
        image_only=image_only,
        sort=sort,
        offset=offset,
        limit=limit,
        db=db,
        state_row_loader=_load_newest_state_rows,
    )
