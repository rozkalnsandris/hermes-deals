from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.current_deals_service import build_current_deals
from app.current_deals_sql_loader import load_sql_ranked_state_rows, materialize_only
from app.db import get_db
from app.schemas import CurrentDealsOut, SourceChain


router = APIRouter()
_ROOT = Path(__file__).resolve().parent / "ui_deals"
_TEMPLATES = Jinja2Templates(directory=_ROOT / "templates")
_HTMX_PATH = _ROOT / "assets" / "htmx.min.js"
_DEFAULT_LIMIT = 250


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _canonical_url(
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
) -> str:
    params: list[tuple[str, str]] = []
    if as_of is not None:
        params.append(("as_of", as_of.isoformat()))
    if q is not None:
        params.append(("q", q))
    if retailer is not None:
        params.append(("retailer", retailer))
    if view != "current":
        params.append(("view", view))
    if app_only:
        params.append(("app_only", "true"))
    if coupon_only:
        params.append(("coupon_only", "true"))
    if discount_only:
        params.append(("discount_only", "true"))
    if image_only:
        params.append(("image_only", "true"))
    if sort != "name":
        params.append(("sort", sort))
    if offset > 0:
        params.append(("offset", str(offset)))
    if limit != _DEFAULT_LIMIT:
        params.append(("limit", str(limit)))
    encoded = urlencode(params)
    return "/ui/deals" + (f"?{encoded}" if encoded else "")


def _load_deals(
    *,
    db: Session,
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
) -> CurrentDealsOut:
    effective_date = as_of or datetime.now(ZoneInfo("Europe/Berlin")).date()
    with materialize_only(view):
        return build_current_deals(
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
            state_row_loader=load_sql_ranked_state_rows,
        )


def _url_for_offset(
    *,
    offset: int,
    as_of: date | None,
    q: str | None,
    retailer: str | None,
    view: str,
    app_only: bool,
    coupon_only: bool,
    discount_only: bool,
    image_only: bool,
    sort: str,
    limit: int,
) -> str:
    return _canonical_url(
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
    )


def _response_headers(response: Response) -> Response:
    response.headers["Vary"] = "HX-Request"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/ui/deals", include_in_schema=False)
def deals_page(
    request: Request,
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
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=500),
    db: Session = Depends(get_db),
) -> Response:
    q = _clean(q)
    retailer = _clean(retailer)
    if retailer is not None:
        retailer = retailer.casefold()

    canonical_url = _canonical_url(
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
    )
    is_htmx = request.headers.get("HX-Request", "").casefold() == "true"
    requested_url = request.url.path + (
        f"?{request.url.query}" if request.url.query else ""
    )
    if not is_htmx and requested_url != canonical_url:
        response = RedirectResponse(canonical_url, status_code=307)
        return _response_headers(response)

    payload = _load_deals(
        db=db,
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
    )

    previous_url = None
    if payload.offset > 0:
        previous_url = _url_for_offset(
            offset=max(0, payload.offset - payload.limit),
            as_of=as_of,
            q=q,
            retailer=retailer,
            view=view,
            app_only=app_only,
            coupon_only=coupon_only,
            discount_only=discount_only,
            image_only=image_only,
            sort=sort,
            limit=limit,
        )

    next_offset = payload.offset + payload.count
    next_url = None
    if payload.count > 0 and next_offset < payload.available_count:
        next_url = _url_for_offset(
            offset=next_offset,
            as_of=as_of,
            q=q,
            retailer=retailer,
            view=view,
            app_only=app_only,
            coupon_only=coupon_only,
            discount_only=discount_only,
            image_only=image_only,
            sort=sort,
            limit=limit,
        )

    clear_search_url = _canonical_url(
        as_of=as_of,
        q=None,
        retailer=retailer,
        view=view,
        app_only=app_only,
        coupon_only=coupon_only,
        discount_only=discount_only,
        image_only=image_only,
        sort=sort,
        offset=0,
        limit=limit,
    )
    context = {
        "payload": payload,
        "as_of": as_of,
        "q": q,
        "retailer": retailer,
        "view": view,
        "app_only": app_only,
        "coupon_only": coupon_only,
        "discount_only": discount_only,
        "image_only": image_only,
        "sort": sort,
        "limit": limit,
        "retailers": [chain.value for chain in SourceChain],
        "canonical_url": canonical_url,
        "clear_search_url": clear_search_url,
        "previous_url": previous_url,
        "next_url": next_url,
        "page_start": payload.offset + 1 if payload.count else 0,
        "page_end": payload.offset + payload.count,
    }

    template_name = "_results.html" if is_htmx else "deals.html"
    response = _TEMPLATES.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
    )
    if is_htmx:
        response.headers["HX-Push-Url"] = canonical_url
    return _response_headers(response)


@router.get("/ui/deals/assets/htmx.min.js", include_in_schema=False)
def deals_htmx_asset() -> FileResponse:
    if not _HTMX_PATH.is_file():
        raise HTTPException(status_code=503, detail="Pinned HTMX asset is not available")
    return FileResponse(
        _HTMX_PATH,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
