from __future__ import annotations

from datetime import date
from time import perf_counter

from fastapi import Depends, FastAPI, Query, Response
from sqlalchemy.orm import Session

from app import current_deals_fast_route as fast_route
from app.current_deals_sql_loader import load_sql_ranked_state_rows
from app.db import get_db
from app.schemas import CurrentDealsOut
from app.weekly_special_api import router as weekly_router


_TARGET_PATH = "/api/v1/deals/current"
_ORIGINAL_GET = FastAPI.get
_CACHE_TTL_SECONDS = 60.0

# Keep the public response/filtering implementation in one place while
# replacing its expensive all-history Python loader with the SQL-ranked path.
fast_route._load_newest_state_rows = load_sql_ranked_state_rows
fast_route._CACHE_TTL_SECONDS = _CACHE_TTL_SECONDS


def _is_postgresql(db: Session) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def installed_fast_current_deals(
    response: Response,
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
    # Test and local SQLite databases are frequently recreated while the
    # process remains alive. Never let a response cache outlive their rows.
    if not _is_postgresql(db):
        fast_route._clear_current_deals_cache()

    started = perf_counter()
    payload = fast_route.fast_current_deals(
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
    )
    duration_ms = (perf_counter() - started) * 1000
    response.headers["Server-Timing"] = (
        f"current-deals-sql;dur={duration_ms:.1f}"
    )
    response.headers["Cache-Control"] = (
        "private, max-age=15, stale-while-revalidate=45"
    )
    response.headers["X-Hermes-Current-Deals-Engine"] = (
        "sql-ranked-active-only"
    )
    return payload


def _remove_temporary_router_registration() -> None:
    weekly_router.routes[:] = [
        route
        for route in weekly_router.routes
        if getattr(route, "endpoint", None) is not fast_route.fast_current_deals
    ]


def _patched_get(app: FastAPI, path: str, *args, **kwargs):
    original_decorator = _ORIGINAL_GET(app, path, *args, **kwargs)
    if path != _TARGET_PATH:
        return original_decorator

    def register(_legacy_endpoint):
        try:
            original_decorator(installed_fast_current_deals)
        finally:
            FastAPI.get = _ORIGINAL_GET
        # Keep app.main.current_deals import-compatible for direct unit calls.
        return _legacy_endpoint

    return register


def install() -> None:
    if getattr(FastAPI, "_hermes_current_route_hook", False):
        return
    _remove_temporary_router_registration()
    FastAPI.get = _patched_get
    FastAPI._hermes_current_route_hook = True


install()
