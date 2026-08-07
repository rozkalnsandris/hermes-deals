from __future__ import annotations

from datetime import date
from time import perf_counter

from fastapi import Depends, FastAPI, Query, Response
from sqlalchemy.orm import Session

from app import current_deals_fast_route as fast_route
from app.current_deals_sql_loader import (
    capture_rank_substage_timings,
    load_sql_ranked_state_rows,
    materialize_only,
)
from app.db import get_db
from app.schemas import CurrentDealsOut
from app.weekly_special_api import router as weekly_router


_TARGET_PATH = "/api/v1/deals/current"
_ORIGINAL_GET = FastAPI.get
_CACHE_TTL_SECONDS = 60.0
_STAGE_METRICS = (
    ("rank", "current-deals-rank"),
    ("filter-sort", "current-deals-filter"),
    ("canonical", "current-deals-canonical"),
    ("model", "current-deals-model"),
)
_RANK_SUBSTAGE_METRICS = (
    ("winner", "current-deals-winner"),
    ("rescue", "current-deals-rescue"),
    ("materialize", "current-deals-materialize"),
)

# Keep the public response/filtering implementation in one place while
# replacing its expensive all-history Python loader with the SQL-ranked path.
fast_route._load_newest_state_rows = load_sql_ranked_state_rows
fast_route._CACHE_TTL_SECONDS = _CACHE_TTL_SECONDS


def _is_postgresql(db: Session) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _duration(timings: dict[str, object], key: str) -> float | None:
    value = timings.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _server_timing_header(
    total_ms: float,
    timings: dict[str, object],
    rank_timings: dict[str, float] | None = None,
) -> str:
    # Preserve the legacy leading metric while adding standards-compliant
    # comma-separated backend stages. Generic stage names intentionally avoid
    # leaking database topology, SQL text, hostnames or internal identifiers.
    metrics = [f"current-deals-sql;dur={total_ms:.1f}"]

    cache_ms = _duration(timings, "cache")
    if cache_ms is not None:
        cache_state = str(timings.get("cache_state") or "unknown")
        if cache_state not in {"hit", "miss"}:
            cache_state = "unknown"
        metrics.append(
            f"current-deals-cache;dur={cache_ms:.1f};desc={cache_state}"
        )

    for timing_key, metric_name in _STAGE_METRICS:
        stage_ms = _duration(timings, timing_key)
        if stage_ms is None:
            continue
        metrics.append(f"{metric_name};dur={stage_ms:.1f}")
        if timing_key == "rank" and rank_timings:
            for substage_key, substage_metric in _RANK_SUBSTAGE_METRICS:
                substage_ms = _duration(rank_timings, substage_key)
                if substage_ms is not None:
                    metrics.append(f"{substage_metric};dur={substage_ms:.1f}")

    return ", ".join(metrics)


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
    with fast_route.capture_current_deals_timings() as timings:
        with capture_rank_substage_timings() as rank_timings:
            with materialize_only(view):
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
    response.headers["Server-Timing"] = _server_timing_header(
        duration_ms,
        timings,
        rank_timings,
    )
    response.headers["Cache-Control"] = (
        "private, max-age=15, stale-while-revalidate=45"
    )
    response.headers["X-Hermes-Current-Deals-Engine"] = (
        "sql-ranked-requested-view"
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
