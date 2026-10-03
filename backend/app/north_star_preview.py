"""Local, synthetic-only UI preview: python -m app.north_star_preview.

No production application import, database connection, collector or network data.
Ephemeral session memory is for this preview only, never a production state store.
"""
import hmac
from datetime import date
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .north_star_data import DEFAULT_DATE, NAV, apply_action, build_context, new_state

BASE = Path(__file__).resolve().parent / "north_star"
COOKIE = "hermes_north_star_demo"
SESSION_TTL = 12 * 60 * 60
MAX_SESSIONS = 200
SESSIONS = {}
app = FastAPI(title="Hermes Deals — synthetic UI preview", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
app.mount("/static", StaticFiles(directory=BASE / "static", check_dir=False), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def session_for(request):
    now = monotonic()
    for key in list(SESSIONS):
        if now - SESSIONS[key]["seen"] > SESSION_TTL:
            del SESSIONS[key]
    session_id = request.cookies.get(COOKIE)
    if session_id not in SESSIONS:
        if len(SESSIONS) >= MAX_SESSIONS:
            del SESSIONS[min(SESSIONS, key=lambda key: SESSIONS[key]["seen"])]
        session_id = token_urlsafe(32)
        SESSIONS[session_id] = {"seen": now, "state": new_state()}
    SESSIONS[session_id]["seen"] = now
    return session_id, SESSIONS[session_id]["state"]


def finish(response, session_id):
    response.set_cookie(COOKIE, session_id, httponly=True, samesite="strict", max_age=SESSION_TTL)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response


def selected_day(value):
    try:
        return date.fromisoformat(value) if value else DEFAULT_DATE
    except ValueError:
        return DEFAULT_DATE


@app.get("/health")
def health():
    return {"status": "ok", "mode": "synthetic-preview", "database": False}


@app.get("/")
def index(request: Request):
    session_id, state = session_for(request)
    params = request.query_params
    view = params.get("view", "overview")
    if view not in {row["id"] for row in NAV}:
        view = "overview"
    context = build_context(state, selected_day(params.get("date")), view, params.get("product"),
                            params.get("q", "")[:120], params.get("retailer", ""), params.get("category", ""), params.get("sort", ""))
    state["notice"] = ""
    return finish(templates.TemplateResponse(request=request, name="index.html", context=context), session_id)


@app.post("/actions/{action}")
async def action_route(action: str, request: Request):
    session_id, state = session_for(request)
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(400, "Invalid form length")
    if length > 8192:
        raise HTTPException(413, "Form too large")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
        raise HTTPException(415, "Use an ordinary HTML form")
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(413, "Form too large")
    try:
        values = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True, max_num_fields=30)
    except ValueError:
        raise HTTPException(400, "Too many form fields")
    form = {key: value[-1] for key, value in values.items()}
    if not hmac.compare_digest(form.get("csrf_token", ""), state["csrf_token"]):
        raise HTTPException(403, "Expired or invalid demo form; reload the page")
    try:
        state["notice"] = apply_action(state, action, form)
    except ValueError as exc:
        state["notice"] = str(exc)
    view = form.get("return_view", "overview")
    if view not in {row["id"] for row in NAV}:
        view = "overview"
    params = {"view": view, "date": selected_day(form.get("date")).isoformat()}
    return finish(RedirectResponse("/?" + urlencode(params), status_code=303), session_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766)
