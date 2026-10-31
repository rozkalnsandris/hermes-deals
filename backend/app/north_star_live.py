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
from time import perf_counter
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_db
from app.household_service import HouseholdConflict, change_household, empty_household
from app.meal_service import BY_ID
from app.north_star_live_data import BOOKLET_RETAILERS, NAV, build_live_context

BASE_PATH = "/ui/home"
ASSETS = Path(__file__).resolve().parent / "north_star"
router = APIRouter(prefix=BASE_PATH)
templates = Jinja2Templates(directory=ASSETS / "templates")
log = logging.getLogger(__name__)

WEEKDAYS_LV = (
    ("Pr", "Pirmdiena"),
    ("Ot", "Otrdiena"),
    ("Tr", "Trešdiena"),
    ("Ce", "Ceturtdiena"),
    ("Pk", "Piektdiena"),
    ("Se", "Sestdiena"),
    ("Sv", "Svētdiena"),
)

SORT_OPTIONS = {"name", "retailer", "newest"}
RETURN_FILTER_VIEWS = {"deals", "history"}


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


def _berlin_today():
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def _ingredient_context(values, day):
    recipe_id = str(values.get("recipe_id") or "").strip()
    ingredient_id = str(values.get("ingredient_id") or "").strip()
    if not recipe_id and not ingredient_id:
        return None
    recipe = BY_ID.get(recipe_id)
    if recipe is None or not ingredient_id:
        raise HTTPException(422, "Recepte vai sastāvdaļa nav atrasta.")
    ingredient = next((item for item in recipe["ingredients"] if item[0] == ingredient_id), None)
    if ingredient is None:
        raise HTTPException(422, "Sastāvdaļa nepieder izvēlētajai receptei.")
    _, ingredient_name, _, unit = ingredient
    recipe_href = BASE_PATH + "/?" + urlencode({"view": "recipes", "date": day.isoformat()})
    anchor = f"ingredient-{recipe_id}-{ingredient_id}"
    deals_href = BASE_PATH + "/?" + urlencode({
        "view": "deals",
        "date": day.isoformat(),
        "recipe_id": recipe_id,
        "ingredient_id": ingredient_id,
    })
    return {
        "recipe_id": recipe_id,
        "recipe_name": recipe["name"],
        "ingredient_id": ingredient_id,
        "ingredient_name": ingredient_name,
        "ingredient_unit": unit,
        "recipe_href": recipe_href + "#" + anchor,
        "deals_href": deals_href,
        "anchor": anchor,
    }


def _return_context(values, day, view):
    target_view = view if view in NAV else "list"
    context = {"view": target_view, "date": day.isoformat()}
    ingredient_context = _ingredient_context(values, day) if target_view == "deals" else None
    if ingredient_context:
        context["recipe_id"] = ingredient_context["recipe_id"]
        context["ingredient_id"] = ingredient_context["ingredient_id"]
    if target_view == "booklets":
        booklet_retailer = values.get("retailer") or "netto"
        if booklet_retailer in dict(BOOKLET_RETAILERS) and booklet_retailer != "netto":
            context["retailer"] = booklet_retailer
        try:
            page = int(values.get("page", "1"))
            context["page"] = page if 1 <= page <= 200 else 1
        except (TypeError, ValueError):
            context["page"] = 1
    if target_view not in RETURN_FILTER_VIEWS:
        return context

    query = (values.get("q") or "")[:100]
    retailer = (values.get("retailer") or "")[:32]
    sort = values.get("sort", "name")
    if sort not in SORT_OPTIONS:
        sort = "name"
    try:
        offset = int(values.get("offset", "0"))
        if not 0 <= offset <= 100000:
            raise ValueError
    except (TypeError, ValueError):
        offset = 0

    if query:
        context["q"] = query
    if retailer and re.fullmatch(r"[a-z0-9_]{1,32}", retailer):
        context["retailer"] = retailer
    if sort != "name":
        context["sort"] = sort
    if offset:
        context["offset"] = offset
    return context


def _return_navigation(values, day, view):
    context = _return_context(values, day, view)
    return {
        "return_context": context,
        "return_href": BASE_PATH + "/?" + urlencode(context),
    }


def _date_navigation(params, day, view):
    filters = {
        key: value
        for key, value in _return_context(params, day, view).items()
        if key not in {"view", "date", "offset", "page"}
    }

    def href(target):
        return BASE_PATH + "/?" + urlencode({"view": view, "date": target.isoformat(), **filters})

    start = day - timedelta(days=day.weekday())
    today = _berlin_today()
    days = []
    for index, (short, name) in enumerate(WEEKDAYS_LV):
        current = start + timedelta(days=index)
        days.append({
            "date": current.isoformat(),
            "short": short,
            "name": name,
            "date_label": current.strftime("%d.%m."),
            "href": href(current),
            "selected": current == day,
        })
    return {
        "selected_date_label": f"{WEEKDAYS_LV[day.weekday()][1]}, {day:%d.%m.%Y}",
        "week_days": days,
        "prev_week_href": href(day - timedelta(days=7)),
        "next_week_href": href(day + timedelta(days=7)),
        "today_href": href(today),
    }


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


def _secure_html(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "HX-Request, HX-History-Restore-Request"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Keep the Origin on same-origin HTML form POSTs (no-referrer can send null).
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https: http: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


def finish(response, request, token):
    response.set_cookie(cookie_name(request), token, httponly=True, secure=public_origin(request).startswith("https:"),
                        samesite="strict", max_age=86400, path="/")
    return _secure_html(response)


def error_context(day, view, message):
    return {"demo": False, "base_path": BASE_PATH, "view": view, "settings": empty_household()["settings"],
            "shopping": {"count": 0}, "selected_date": day.isoformat(), "week_label": day.strftime("%d.%m.%Y"),
            "prev_date": (day - timedelta(days=7)).isoformat(), "next_date": (day + timedelta(days=7)).isoformat(),
            "read_error": True, "error_message": message, "selected_product": None, "notice": "", "has_offers": False}


def _safe_error_day(value):
    try:
        return selected_day(value)
    except HTTPException:
        return _berlin_today()


def _safe_error_view(value):
    return value if value in NAV else "overview"


def _error_title(status):
    if status == 403:
        return "Forma nav derīga"
    if status == 404:
        return "Sadaļa nav atrasta"
    if status in {400, 413, 415, 422}:
        return "Pārbaudi ievadītos datus"
    if status == 409:
        return "Dati ir mainījušies"
    return "Dati pašlaik nav pieejami"


def _render_http_error(request, status, message, *, day=None, view=None, action_label=None, action_href=None):
    day = day or _safe_error_day(request.query_params.get("date"))
    view = _safe_error_view(view or request.query_params.get("view"))
    safe_message = message if status < 500 else "Darbība pašlaik nav pieejama. Mēģini vēlreiz pēc brīža."
    destination = action_href or BASE_PATH + "/?" + urlencode({"view": view, "date": day.isoformat()})
    if action_label is None:
        action_label = "Atvērt svaigu formu" if status == 403 else "Atgriezties pārskatā" if status == 404 else "Atgriezties un labot"
    context = error_context(day, view, safe_message)
    context.update({
        "fragment": False,
        "csrf_token": "",
        "test_database": os.getenv("APP_ENV") == "test",
        "error_status": status,
        "error_title": _error_title(status),
        "error_action_label": action_label,
        "error_action_href": destination,
    })
    response = templates.TemplateResponse(request=request, name="live.html", context=context, status_code=status)
    return _secure_html(response)


async def ui_http_exception_handler(request: Request, exc: HTTPException):
    path = request.url.path
    if path not in {BASE_PATH, BASE_PATH + "/"} and not path.startswith(BASE_PATH + "/actions/"):
        return await http_exception_handler(request, exc)
    detail = exc.detail if isinstance(exc.detail, str) else "Pieprasījumu nevar apstrādāt."
    return _render_http_error(request, exc.status_code, detail)


def render(request, context, *, status=200):
    token = csrf_token(request)
    # Browser history must re-read a full document, never reuse household HTML.
    context["fragment"] = (
        request.method == "GET"
        and status == 200
        and request.headers.get("HX-Request", "").lower() == "true"
        and request.headers.get("HX-History-Restore-Request", "").lower() != "true"
    )
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
        booklet_page = int(params.get("page", "1")) if view == "booklets" else 1
        if not 1 <= booklet_page <= 200:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Norādi bukleta lapu no 1 līdz 200.")
    booklet_retailer = params.get("retailer", "netto") if view == "booklets" else "netto"
    if view == "booklets" and booklet_retailer not in dict(BOOKLET_RETAILERS):
        raise HTTPException(422, "Neatbalstīts bukleta veikals.")
    ingredient_context = _ingredient_context(params, day)
    sort = params.get("sort", "name")
    if sort not in SORT_OPTIONS:
        raise HTTPException(422, "Nederīga kārtošanas izvēle.")
    try:
        offset = int(params.get("offset", "0"))
        if not 0 <= offset <= 100000:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Nederīgs lapas numurs.")
    context_started = perf_counter()
    try:
        context = build_live_context(db, household_key(), day, view=view, query=params.get("q", "")[:100],
                                     retailer=params.get("retailer", "")[:32], sort=sort, product=params.get("product"), offset=offset, booklet_page=booklet_page, booklet_retailer=booklet_retailer)
    except SQLAlchemyError:
        db.rollback()
        log.warning("North-star data read failed; check database and migration 0008")
        context = error_context(day, view, "Pārbaudi datubāzes savienojumu un mājsaimniecības datu sagatavošanu.")
        context.update(_date_navigation(params, day, view))
        context.update(_return_navigation(params, day, view))
        context["ingredient_context"] = ingredient_context if view == "deals" else None
        return render(request, context, status=503)
    context_done = perf_counter()
    context.update(_date_navigation(params, day, view))
    context.update(_return_navigation(params, day, view))
    context["ingredient_context"] = ingredient_context if view == "deals" else None
    if params.get("saved") == "1":
        context["notice"] = "Izmaiņas saglabātas."
        context["notice_kind"] = "success"
    response = render(request, context)
    response.headers["Server-Timing"] = (
        f"home-context;dur={(context_done - context_started) * 1000:.1f}, "
        f"home-render;dur={(perf_counter() - context_done) * 1000:.1f}"
    )
    return response


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
        day = _safe_error_day(form.get("date"))
        view = _safe_error_view(form.get("return_view"))
        return _render_http_error(
            request,
            403,
            "Veidlapas derīgums beidzies. Atver svaigu formu un pārbaudi datus pirms atkārtotas saglabāšanas.",
            day=day,
            view=view,
            action_label="Atvērt svaigu formu",
            action_href=BASE_PATH + "/?" + urlencode({"view": view, "date": day.isoformat()}),
        )
    day = selected_day(form.get("date"))
    ingredient_context = (
        _ingredient_context(form, day)
        if action == "ingredient_bind" and form.get("recipe_id")
        else None
    )
    requested_view = form.get("return_view", "list")
    return_context = _return_context(form, day, requested_view)
    view = return_context["view"]
    try:
        change_household(db, household_key(), version, action, form)
    except ValueError as exc:
        context = build_live_context(
            db,
            household_key(),
            day,
            view=view,
            query=return_context.get("q", ""),
            retailer=return_context.get("retailer", ""),
            sort=return_context.get("sort", "name"),
            offset=return_context.get("offset", 0),
            booklet_page=return_context.get("page", 1),
            booklet_retailer=return_context.get("retailer", "netto") if view == "booklets" else "netto",
        )
        context.update(_date_navigation(return_context, day, view))
        context.update(_return_navigation(return_context, day, view))
        context["ingredient_context"] = ingredient_context if view == "deals" else None
        conflict = isinstance(exc, HouseholdConflict)
        context["notice"] = str(exc)
        context["notice_kind"] = "conflict" if conflict else "error"
        context["notice_action_href"] = context["return_href"]
        context["notice_action_label"] = "Atsvaidzināt datus" if conflict else "Atgriezties pie formas"
        return render(request, context, status=409 if conflict else 422)
    except SQLAlchemyError:
        db.rollback()
        context = error_context(day, view, "Izmaiņas neizdevās saglabāt. Pārlādē lapu un pārbaudi sarakstu.")
        context.update(_date_navigation(return_context, day, view))
        context.update(_return_navigation(return_context, day, view))
        context["ingredient_context"] = ingredient_context if view == "deals" else None
        return render(request, context, status=503)
    if action == "ingredient_bind" and ingredient_context:
        destination = {"view": "recipes", "date": day.isoformat(), "saved": "1"}
        location = BASE_PATH + "/?" + urlencode(destination) + "#" + ingredient_context["anchor"]
        return finish(RedirectResponse(location, status_code=303), request, token)
    destination = {**return_context, "saved": "1"}
    if action == "price_eligibility":
        destination["product"] = form["product_id"]
    return finish(RedirectResponse(BASE_PATH + "/?" + urlencode(destination), status_code=303), request, token)


def install(app):
    app.include_router(router)
    app.mount(BASE_PATH + "/static", StaticFiles(directory=ASSETS / "static"), name="north-star-static")
    app.add_exception_handler(HTTPException, ui_http_exception_handler)
