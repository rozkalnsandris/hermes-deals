"""Read-only HZ46 PDF Review overlay bound to an immutable projection receipt.

This layer exposes only Review markers from exact PDF geometry after an exact
page-order proof. It never creates a Hermes product, offer, price, or link.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from app.netto_html_publications import validated_pages

_SHA = re.compile(r"[0-9a-f]{64}\Z")

# HZ46 Review evidence is pinned to the separately authorized, retained,
# SHA-verified marker manifest and page-scoped projection. Runtime placement
# under netto-html/review-layers remains a separate LIVE gate.
_TRUSTED_REVIEW_LAYERS = {
    "hz46_hasb_4": {
        "store": "5659",
        "group": "regionale-hz",
        "publication_sha256": "68184db39b6cb9878d6eab2e804ab767310390135e5f12772762329c661ac087",
        "pdf_sha256": "9d6337beb029977cf8c119cbe2d216b4aab5052523c5e49e6bad0b102418f8cf",
        "image_manifest_sha256": "a23db82f42f2fc2ccc81802aab65b8454979d29c64967077eada59523e87764c",
        "alignment_review_sha256": "0b7fe988e655597480235d927b20e9b14fa920525655e27400a5f4a333c28b93",
        "review_markers_sha256": "344ee5f838d922cb0db42c85cb2a497459c81e2233fcea6c0db3c4a5c567b709",
        "projection_sha256": "24d1b980c06bbdbb0c58cfe8f00cb4153022f0053684ce5a8e565034e0ea570c",
        "page_count": 80,
        "candidate_count": 686,
    },
}


def _read_verified(path: Path, root: Path, limit: int, digest: str) -> bytes:
    if type(digest) is not str or _SHA.fullmatch(digest) is None:
        raise ValueError("Review projection digest is not enabled")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked Review projection")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved.suffix != ".json":
        raise ValueError("Review projection outside approved storage")
    with resolved.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit or sha256(raw).hexdigest() != digest:
        raise ValueError("Review projection size/hash mismatch")
    return raw


def _rect(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError("Missing Review rectangle")
    values = [raw.get(key) for key in ("left", "top", "width", "height")]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("Invalid Review rectangle")
    left, top, width, height = map(float, values)
    if (left < 0 or top < 0 or width <= 0 or height <= 0
            or left + width > 1.000001 or top + height > 1.000001):
        raise ValueError("Out-of-page Review rectangle")
    return {"left": left, "top": top, "width": width, "height": height}


def review_only_hotspots(
    root: Path, *, store_id: str, snapshot_id: str, manifest_sha256: str,
    record: dict, day: date, valid_from: date, valid_until: date,
) -> dict[int, list[dict]]:
    slug = record.get("slug")
    trust = _TRUSTED_REVIEW_LAYERS.get(slug) if type(slug) is str else None
    # Collector snapshot/manifest IDs can rotate while the exact publication bytes
    # stay unchanged. Review eligibility therefore binds to the immutable
    # publication identity plus the retained projection provenance below.
    if (trust is None or store_id != trust["store"]
            or record.get("publication_sha256") != trust["publication_sha256"]
            or type(day) is not date or type(valid_from) is not date
            or type(valid_until) is not date or not valid_from <= day <= valid_until):
        return {}
    projection_sha = trust.get("projection_sha256")
    marker_sha = trust.get("review_markers_sha256")
    if (type(projection_sha) is not str or _SHA.fullmatch(projection_sha) is None
            or type(marker_sha) is not str or _SHA.fullmatch(marker_sha) is None):
        return {}

    try:
        root = root.resolve(strict=True)
        evidence_root = root / "netto-html"
        publication_path = Path(record["publication_path"])
        publication_raw = _read_verified(
            publication_path, evidence_root, 2 * 1024 * 1024,
            trust["publication_sha256"],
        )
        publication = json.loads(publication_raw)
        identifiers = validated_pages(publication)
        if len(identifiers) != trust["page_count"]:
            raise ValueError("Publication page count differs from Review trust")

        review_root = evidence_root / "review-layers"
        location = review_root / f"{slug}-{projection_sha[:12]}.json"
        raw = _read_verified(location, review_root, 8 * 1024 * 1024, projection_sha)
        payload = json.loads(raw)
        exact = {
            "format": "hermes.netto.pdf_review_projection.v1",
            "state": "REVIEW_ONLY",
            "store_id": trust["store"],
            "group": trust["group"],
            "slug": slug,
            "pdf_sha256": trust["pdf_sha256"],
            "publication_sha256": trust["publication_sha256"],
            "image_manifest_sha256": trust["image_manifest_sha256"],
            "alignment_review_sha256": trust["alignment_review_sha256"],
            "review_markers_sha256": marker_sha,
            "page_count": trust["page_count"],
            "candidate_count": trust["candidate_count"],
            "automatic_offer_links": 0,
            "verified_product_identities": 0,
        }
        if not isinstance(payload, dict) or any(payload.get(key) != value for key, value in exact.items()):
            raise ValueError("Review projection provenance mismatch")
        rows = payload.get("pages")
        if not isinstance(rows, list) or len(rows) != trust["page_count"]:
            raise ValueError("Incomplete Review projection")

        pages: dict[int, list[dict]] = {}
        seen: set[str] = set()
        total = 0
        for number, (row, identifier) in enumerate(zip(rows, identifiers), 1):
            if (not isinstance(row, dict)
                    or row.get("publication_page_number") != number
                    or row.get("pdf_page_number") != number
                    or row.get("publication_page_identifier") != identifier):
                raise ValueError("Review projection page identity mismatch")
            candidates = row.get("candidates")
            if not isinstance(candidates, list):
                raise ValueError("Missing Review candidates")
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    raise ValueError("Malformed Review candidate")
                cid = candidate.get("candidate_id")
                title = candidate.get("candidate_text_unverified")
                prices = candidate.get("printed_normal_price_candidates_unverified")
                reasons = candidate.get("review_reasons")
                if (type(cid) is not str or not cid or len(cid) > 160 or cid in seen
                        or candidate.get("state") != "REVIEW_ONLY"
                        or candidate.get("source") != "pdf_review_only"
                        or candidate.get("hermes_offer_link") is not None
                        or candidate.get("verified_product_identity") is not None):
                    raise ValueError("Review candidate is not fail-closed")
                if title is not None and (type(title) is not str or len(title) > 1200):
                    raise ValueError("Unbounded Review title")
                if (not isinstance(prices, list)
                        or any(type(value) is not str or len(value) > 30 for value in prices)
                        or not isinstance(reasons, list) or not reasons
                        or any(type(value) is not str or len(value) > 140 for value in reasons)):
                    raise ValueError("Malformed Review metadata")
                seen.add(cid)
                total += 1
                pages.setdefault(number, []).append({
                    "rectangle": _rect(candidate.get("rectangle")),
                    "title": (title or "Review kandidāts").strip()[:1200],
                    "printed_prices": prices,
                    "candidate_id": cid,
                    "source": "pdf_review_only",
                })
        if total != trust["candidate_count"] or total != len(seen):
            raise ValueError("Review projection candidate count mismatch")
        return pages
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        return {}
