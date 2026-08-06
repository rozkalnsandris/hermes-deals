from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Query
from sqlalchemy.orm import Session

from app import current_deals_fast_route as fast_route
from app.db import get_db
from app.schemas import CurrentDealsOut
from app.weekly_special_api import router as weekly_router


_TARGET_PATH = "/api/v1/deals/current"
_ORIGINAL_GET = FastAPI.get


def _is_postgresql(db: Session) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def installed_fast_current_deals(
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
    return fast_route.fast_current_deals(
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
