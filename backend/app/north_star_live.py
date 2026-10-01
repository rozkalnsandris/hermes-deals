"""Production data boundary for the new UI, under the existing private ingress.

No schema creation or seed data at startup. The operator applies migration 0008
separately. All authorized clients of this single-family deployment share the
server-configured household; client parameters cannot select another household.
"""
import hmac
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.household_service import HouseholdConflict, change_household, empty_household
from app.north_star_live_data import NAV, build_live_context

BASE_PATH = "/ui/home"
ASSETS = Path(__file__).resolve().parent / "north_star"
router = APIRouter(prefix=BASE_PATH)
templates = Jinja2Templates(directory=ASSETS / "templates")
log = logging.getLogger(__name__)


def household_key():
    key = os.getenv("HERMES_HOUSEHOLD_ID", "home")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key):
        raise HTTPException(503, "Mājsaimniecība nav konfigurēta.")
    return key


def selected_day(value):
    try:
        selected = date.fromisoformat(value) if value else datetime.now(ZoneInfo("Europe/Berlin")).date()
        if not 1970 <= selected.year <= 2100:
            raise ValueError
        return selected
    except ValueError:
        raise HTTPException(422, "Norādi datumu formātā GGGG-MM-DD (1970–2100).")


def public_origin(request):
    configured = os.getenv("HERMES_PUBLIC_ORIGIN")
    origin = configured.rstrip("/") if configured else f"{request.url.scheme}://{request.url.netloc}"
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise HTTPException(503, "Vietnes adrese nav konfigurēta pareizi.")
    return origin


def cookie_name(request):
    return "__Host-hermes_home_csrf" if public_origin(request).startswith("https:") else "hermes_home_csrf"


def csrf_token(request):
    value = request.cookies.get(cookie_name(request), "")
    return value if re.fullmatch(r"[A-Za-z0-9_-]{43}", value) else token_urlsafe(32)


def finish(response, request, token):
    response.set_cookie(cookie_name(request), token, httponly=True, secure=public_origin(request).startswith("https:"),
                        samesite="strict", max_age=86400, path="/")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Keep the Origin on same-origin HTML form POSTs (no-referrer can send null).
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https: http: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


def error_context(day, view, message):
    return {"demo": False, "base_path": BASE_PATH, "view": view, "settings": empty_household()["settings"],
            "shopping": {"count": 0}, "selected_date": day.isoformat(), "week_label": day.strftime("%d.%m.%Y"),
            "prev_date": (day - timedelta(days=7)).isoformat(), "next_date": (day + timedelta(days=7)).isoformat(),
            "read_error": True, "error_message": message, "selected_product": None, "notice": "", "has_offers": False}


def render(request, context, *, status=200):
    token = csrf_token(request)
    context["csrf_token"] = token
    context["test_database"] = os.getenv("APP_ENV") == "test"
    return finish(templates.TemplateResponse(request=request, name="live.html", context=context, status_code=status), request, token)


@router.get("")
@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    params = request.query_params
    day = selected_day(params.get("date"))
    view = params.get("view", "overview")
    if view not in NAV:
        raise HTTPException(404, "Sadaļa nav atrasta.")
    try:
        offset = int(params.get("offset", "0"))
        if not 0 <= offset <= 100000:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Nederīgs lapas numurs.")
    try:
        context = build_live_context(db, household_key(), day, view=view, query=params.get("q", "")[:100],
                                     retailer=params.get("retailer", "")[:32], product=params.get("product"), offset=offset)
    except SQLAlchemyError:
        db.rollback()
        log.warning("North-star data read failed; check database and migration 0008")
        return render(request, error_context(day, view, "Pārbaudi datubāzes savienojumu un mājsaimniecības datu sagatavošanu."), status=503)
    if params.get("saved") == "1":
        context["notice"] = "Izmaiņas saglabātas ģimenes sarakstā."
    return render(request, context)


@router.post("/actions/{action}")
async def change(action: str, request: Request, db: Session = Depends(get_db)):
    origin = public_origin(request)
    if request.headers.get("origin", "").rstrip("/") != origin:
        raise HTTPException(403, "Atver veidlapu šajā pašā vietnē.")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Izmanto lapas veidlapu.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise HTTPException(413, "Veidlapa ir pārāk liela.")
    try:
        values = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=30)
        form = {key: rows[-1] for key, rows in values.items()}
        version = int(form.get("version", ""))
        if version < 0:
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Nederīga veidlapa. Pārlādē lapu.")
    token = request.cookies.get(cookie_name(request), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token) or not hmac.compare_digest(token.encode(), form.get("csrf_token", "").encode()):
        raise HTTPException(403, "Veidlapas derīgums beidzies. Pārlādē lapu.")
    day = selected_day(form.get("date"))
    view = form.get("return_view", "list")
    if view not in NAV:
        view = "list"
    try:
        change_household(db, household_key(), version, action, form)
    except ValueError as exc:
        context = build_live_context(db, household_key(), day, view=view)
        context["notice"] = str(exc)
        return render(request, context, status=409 if isinstance(exc, HouseholdConflict) else 422)
    except SQLAlchemyError:
        db.rollback()
        return render(request, error_context(day, view, "Izmaiņas neizdevās saglabāt. Pārlādē lapu un pārbaudi sarakstu."), status=503)
    return finish(RedirectResponse(BASE_PATH + "/?" + urlencode({"view": view, "date": day.isoformat(), "saved": "1"}), status_code=303), request, token)


def install(app):
    app.include_router(router)
    app.mount(BASE_PATH + "/static", StaticFiles(directory=ASSETS / "static"), name="north-star-static")
