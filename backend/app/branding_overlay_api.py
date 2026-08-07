from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
import struct

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response


router = APIRouter()
_UI_DIR = Path(__file__).resolve().parent / "ui"
_UI_INDEX_PATH = _UI_DIR / "index.html"
_UI_REVIEW_PATH = _UI_DIR / "review.html"
_LOGO_SVG_PATH = _UI_DIR / "assets" / "deals-logo.svg"
_PNG_DATA_PREFIX = 'href="data:image/png;base64,'
_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}
_FAVICON_OVERLAY = """  <!-- hermes-branding-overlay:start -->
  <link rel=\"icon\" type=\"image/png\" sizes=\"96x96\" href=\"/ui/assets/deals-logo.png\">
  <link rel=\"shortcut icon\" type=\"image/x-icon\" href=\"/ui/assets/deals-logo.ico\">
  <!-- hermes-branding-overlay:end -->
"""
_BRAND_LOGO = (
    '<img class="project-logo" src="/ui/assets/deals-logo.svg" '
    'width="34" height="34" alt="">'
)
_WEEKLY_BRAND_LOGO = (
    '<img class="project-logo weekly-project-logo" '
    'src="/ui/assets/deals-logo.svg" width="32" height="32" alt="">'
)


def _read_ui_html(path: Path) -> str:
    if not path.exists():
        raise HTTPException(status_code=503, detail="UI bundle is not available")
    return path.read_text(encoding="utf-8")


def _insert_favicons(html: str) -> str:
    if "hermes-branding-overlay:start" in html:
        raise RuntimeError("branding overlay already present")
    lines = html.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if '<link rel="icon" href="data:image/svg+xml,' in line:
            lines.insert(index + 1, _FAVICON_OVERLAY)
            return "".join(lines)
    raise RuntimeError("legacy favicon anchor is missing")


def _brand_main_ui(html: str) -> str:
    branded = _insert_favicons(html)
    brand_anchor = '<a class="brand-lockup" href="#home"><svg class="brand-leaf"'
    branded_anchor = (
        '<a class="brand-lockup" href="#home">'
        + _BRAND_LOGO
        + '<svg class="brand-leaf" hidden'
    )
    if branded.count(brand_anchor) != 2:
        raise RuntimeError("main UI brand-lockup contract changed")
    branded = branded.replace(brand_anchor, branded_anchor)

    weekly_anchor = (
        '            <a class="weekly-brand" href="#home" '
        'aria-label="Hermes Deals sākums">\n'
        '              <svg class="weekly-brand-mark"'
    )
    branded_weekly = (
        '            <a class="weekly-brand" href="#home" '
        'aria-label="Hermes Deals sākums">\n'
        f'              {_WEEKLY_BRAND_LOGO}\n'
        '              <svg class="weekly-brand-mark" hidden'
    )
    if branded.count(weekly_anchor) != 1:
        raise RuntimeError("weekly brand contract changed")
    return branded.replace(weekly_anchor, branded_weekly, 1)


def _brand_review_ui(html: str) -> str:
    return _insert_favicons(html)


@lru_cache(maxsize=1)
def _logo_png_bytes() -> bytes:
    if not _LOGO_SVG_PATH.exists():
        raise RuntimeError("project logo SVG is unavailable")
    svg = _LOGO_SVG_PATH.read_text(encoding="utf-8")
    start = svg.find(_PNG_DATA_PREFIX)
    if start < 0:
        raise RuntimeError("project logo SVG does not embed PNG source")
    start += len(_PNG_DATA_PREFIX)
    end = svg.find('"', start)
    if end < 0:
        raise RuntimeError("project logo PNG data URI is malformed")
    try:
        png = base64.b64decode(svg[start:end], validate=True)
    except ValueError as exc:
        raise RuntimeError("project logo PNG base64 is invalid") from exc
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) < 24:
        raise RuntimeError("project logo embedded image is not a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if (width, height) != (96, 96):
        raise RuntimeError("project logo PNG must be exactly 96x96")
    return png


@lru_cache(maxsize=1)
def _logo_ico_bytes() -> bytes:
    png = _logo_png_bytes()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        96,
        96,
        0,
        0,
        1,
        32,
        len(png),
        22,
    )
    return header + entry + png


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def branded_family_ui() -> HTMLResponse:
    try:
        html = _brand_main_ui(_read_ui_html(_UI_INDEX_PATH))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Deals branding overlay unavailable: {exc}",
        ) from exc
    return HTMLResponse(html)


@router.get("/ui/review", response_class=HTMLResponse, include_in_schema=False)
def branded_review_ui() -> HTMLResponse:
    try:
        html = _brand_review_ui(_read_ui_html(_UI_REVIEW_PATH))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Deals review branding unavailable: {exc}",
        ) from exc
    return HTMLResponse(html)


@router.get("/ui/assets/deals-logo.svg", include_in_schema=False)
def deals_logo_svg() -> FileResponse:
    if not _LOGO_SVG_PATH.exists():
        raise HTTPException(status_code=503, detail="Deals logo SVG is unavailable")
    return FileResponse(
        _LOGO_SVG_PATH,
        media_type="image/svg+xml",
        headers=_CACHE_HEADERS,
    )


@router.get("/ui/assets/deals-logo.png", include_in_schema=False)
def deals_logo_png() -> Response:
    try:
        body = _logo_png_bytes()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=body, media_type="image/png", headers=_CACHE_HEADERS)


@router.get("/ui/assets/deals-logo.ico", include_in_schema=False)
def deals_logo_ico() -> Response:
    try:
        body = _logo_ico_bytes()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=body, media_type="image/x-icon", headers=_CACHE_HEADERS)
