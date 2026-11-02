"""Offline, read-only Netto 5659 Publitas hotspot candidates for human Review.

The caller must first verify the selected-store manifest, publication identity,
validity and the SHA supplied here against immutable source evidence. Equality
to the supplied SHA is a byte-integrity check, not proof of offer ownership.
Nothing in this module creates a product/offer match or a clickable link.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import math
import re

from app.netto_html_publications import validated_pages

_STORE = "5659"
_SHA = re.compile(r"[0-9a-f]{64}")
_MAX_PUBLICATION_BYTES = 2 * 1024 * 1024
_MAX_HOTSPOTS_PER_SPREAD = 1000


def _positive_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Publitas product/hotspot ID must be a positive integer")
    return value


def _box(position: object) -> tuple[float, float, float, float]:
    if not isinstance(position, dict):
        raise ValueError("Missing publisher hotspot rectangle")
    coordinates = []
    for axis in ("left", "top", "width", "height"):
        item = position.get(axis)
        if type(item) not in (float, int) or not math.isfinite(item):
            raise ValueError("Non-finite or missing publisher coordinate")
        if not 0 <= item <= 1:
            raise ValueError("Publisher coordinate outside normalized spread")
        coordinates.append(float(item))
    left, top, width, height = coordinates
    if width <= 0 or height <= 0 or left + width > 1 or top + height > 1:
        raise ValueError("Unbounded or empty publisher rectangle")
    return left, top, width, height


def _verified_page_size(publication: dict) -> tuple[float, float] | None:
    """Use the same source-declared image size for each page in a spread.

    Publitas REST v1 declares image sizes per page and normalized positions
    relative to the spread. No size evidence means no page-local projection.
    """
    sizes = publication.get("sizes")
    values = sizes.get("at1600") if isinstance(sizes, dict) else None
    if not isinstance(values, dict):
        return None
    width, height = values.get("width"), values.get("height")
    if any(type(v) not in (int, float) or not math.isfinite(v) or
           not 1 <= v <= 10000 for v in (width, height)):
        return None
    return float(width), float(height)


def scan_netto_review_candidates(
    publication_bytes: bytes, publication_sha256: str, *,
    store_id: str, day: date, valid_from: date, valid_until: date,
) -> dict:
    """Project observed product hotspots, never offer IDs, into page-local boxes.

    This has no network, OCR, database, persistence or browser side effects.
    Review-only output is not a verified publisher-ID -> Netto-SKU bridge.
    """
    if store_id != _STORE or type(store_id) is not str:
        raise ValueError("Wrong selected Netto store")
    if any(type(value) is not date for value in (day, valid_from, valid_until)):
        raise ValueError("Exact publication validity dates are required")
    if not valid_from <= day <= valid_until or (valid_until - valid_from).days > 14:
        raise ValueError("Date outside verified publication window")
    if not isinstance(publication_bytes, bytes) or len(publication_bytes) > _MAX_PUBLICATION_BYTES:
        raise ValueError("Missing or oversized immutable publication bytes")
    if not isinstance(publication_sha256, str) or not _SHA.fullmatch(publication_sha256):
        raise ValueError("Invalid immutable publication SHA")
    if sha256(publication_bytes).hexdigest() != publication_sha256:
        raise ValueError("Publication SHA does not match source bytes")
    try:
        publication = json.loads(publication_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unusable publisher publication JSON") from exc
    paths = validated_pages(publication)
    spreads = publication["spreads"]
    page_dimensions = _verified_page_size(publication)
    seen_hotspots: set[int] = set()
    candidates = []
    first_page = 1
    for spread_index, spread in enumerate(spreads):
        pages = spread["pages"]
        if len(pages) not in (1, 2):
            raise ValueError("Publisher spread must contain one or two pages")
        hotspots = spread.get("hotspots", [])
        if not isinstance(hotspots, list) or len(hotspots) > _MAX_HOTSPOTS_PER_SPREAD:
            raise ValueError("Invalid publisher hotspot list")
        for hotspot in hotspots:
            if not isinstance(hotspot, dict):
                raise ValueError("Malformed publisher hotspot")
            if hotspot.get("type") != "product":
                continue
            hotspot_id = _positive_id(hotspot.get("id"))
            if hotspot_id in seen_hotspots:
                raise ValueError("Duplicated publisher hotspot ID")
            seen_hotspots.add(hotspot_id)
            products = hotspot.get("products")
            if not isinstance(products, list) or not 1 <= len(products) <= 100:
                raise ValueError("Missing or ambiguous publisher products")
            ids = []
            for item in products:
                if not isinstance(item, dict):
                    raise ValueError("Malformed publisher product reference")
                ids.append(_positive_id(item.get("id")))
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate product ID inside hotspot")
            left, top, width, height = _box(hotspot.get("position"))
            identity = {
                "hotspot_id": hotspot_id,
                "publisher_product_ids": sorted(ids),
                "spread_index": spread_index,
                "product_count": len(ids),
                "status": "review_only",
            }
            if page_dimensions is None:
                candidates.append({
                    **identity,
                    "page_number": None,
                    "rectangle": None,
                    "reason": "source_page_dimensions_unverified",
                })
                continue
            # Each page shares the publisher-declared at1600 dimensions.
            # For a two-page spread the equal page widths yield a 0.5 split.
            count = len(pages)
            for index in range(count):
                page_start, page_end = index / count, (index + 1) / count
                visible_left = max(left, page_start)
                visible_right = min(left + width, page_end)
                if visible_right <= visible_left:
                    continue
                candidates.append({
                    **identity,
                    "page_number": first_page + index,
                    "rectangle": {
                        "left": round((visible_left - page_start) * count, 9),
                        "top": round(top, 9),
                        "width": round((visible_right - visible_left) * count, 9),
                        "height": round(height, 9),
                    },
                    "reason": "publisher_hotspot_only_offer_identity_unproven",
                })
        first_page += len(pages)
    return {
        "state": "review_only",
        "store_id": _STORE,
        "publication_sha256": publication_sha256,
        "selected_date": day.isoformat(),
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "page_count": len(paths),
        "source_page_dimensions": (
            {"width": page_dimensions[0], "height": page_dimensions[1], "size": "at1600"}
            if page_dimensions else None
        ),
        "candidates": candidates,
        "verified_offer_links": 0,
    }
