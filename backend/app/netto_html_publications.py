"""Netto selected-store booklet publication metadata; no PDF acquisition.

This module never guesses validity or offer/product identity. Call it only after
the existing HTML collector has proven the selected 5659 cookie and store URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re

import httpx

from app.netto_store_prospect import extract_prospect_validity
from app.structured_source_shadow import extract_netto_group_slug

_SLUG = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PATH = re.compile(r"/[A-Za-z0-9_./-]+")
_MAX_HTML = 8 * 1024 * 1024
_MAX_JSON = 2 * 1024 * 1024


@dataclass(frozen=True)
class PublicationCapture:
    slug: str
    start: date
    end: date
    validity_text: str
    viewer_url: str
    viewer_html: bytes
    publication_api_url: str
    publication_json: bytes


def validated_pages(payload: dict) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("Netto publication must be a JSON object")
    spreads = payload.get("spreads")
    if not isinstance(spreads, list) or not spreads:
        raise ValueError("Invalid Netto publication spreads")
    paths: list[str] = []
    for spread in spreads:
        if not isinstance(spread, dict):
            raise ValueError("Invalid Netto publication spread")
        pages = spread.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("Missing Netto publication spread pages")
        if any(not isinstance(page, str) for page in pages):
            raise ValueError("Invalid Netto publication page type")
        paths.extend(pages)
        if len(paths) > 200:
            raise ValueError("Too many Netto publication pages")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate Netto publication page paths")
    if any(not _PATH.fullmatch(path)
           or path.startswith("//")
           or ".." in path.split("/") for path in paths):
        raise ValueError("Invalid Netto publication asset path")
    return paths


def _response(client: httpx.Client, url: str, content_type: str, limit: int) -> bytes:
    response = client.get(url, headers={"Accept": content_type})
    if response.is_redirect or str(response.url) != url:
        raise ValueError("Netto publication redirect or URL drift")
    response.raise_for_status()
    if content_type not in response.headers.get("content-type", "").lower():
        raise ValueError("Unexpected Netto publication content type")
    data = response.content
    if len(data) > limit:
        raise ValueError("Netto publication response too large")
    return data


def fetch_one(client: httpx.Client, slug: str, expected_start: date) -> PublicationCapture:
    if not _SLUG.fullmatch(slug) or not isinstance(expected_start, date):
        raise ValueError("Invalid Netto booklet teaser identity")
    viewer_url = f"https://wochenprospekt.netto-online.de/{slug}/?storeid=5659"
    viewer_html = _response(client, viewer_url, "text/html", _MAX_HTML)
    start, end, validity_text = extract_prospect_validity(viewer_html)
    if start != expected_start or not start <= end or (end - start).days > 14:
        raise ValueError("Netto viewer validity disagrees with store teaser")
    group = extract_netto_group_slug(viewer_html.decode("utf-8", errors="replace"))
    if not isinstance(group, str) or not _SLUG.fullmatch(group):
        raise ValueError("Invalid Netto Publitas group identity")
    publication_api_url = (
        f"https://api.publitas.com/v1/groups/{group}/publications/{slug}.json"
    )
    raw = _response(client, publication_api_url, "application/json", _MAX_JSON)
    try:
        publication = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid Netto publication JSON") from exc
    validated_pages(publication)
    return PublicationCapture(
        slug, start, end, validity_text,
        viewer_url, viewer_html, publication_api_url, raw,
    )


def fetch_publications(starts: dict[str, str]) -> tuple[list[PublicationCapture], list[str]]:
    """Best-effort auxiliary metadata fetch; offers never depend on success.

    Each failure is recorded by slug but never converted into publication pages.
    """
    if not starts:
        return [], []
    if len(starts) > 4:
        return [], sorted(starts)
    captures: list[PublicationCapture] = []
    failures: list[str] = []
    with httpx.Client(
        follow_redirects=False, timeout=25,
        headers={"User-Agent": "Mozilla/5.0 HermesDeals", "Accept-Language": "de-DE"},
    ) as client:
        for slug, value in sorted(starts.items()):
            try:
                capture = fetch_one(client, slug, date.fromisoformat(value))
            except (ValueError, TypeError, httpx.HTTPError):
                failures.append(slug)
            else:
                captures.append(capture)
    return captures, failures
