#!/usr/bin/env python3
"""Project Review-only Netto PDF markers onto a proven Publitas page order.

No network, DB, collector, publication write, offer mapping, or UI activation.
The output remains REVIEW_ONLY and cannot create a Hermes product relationship.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re

FORMAT = "hermes.netto.pdf_review_projection.v1"
MARKER_FORMAT = "hermes.netto.pdf_review_markers.v1"
ALIGNMENT_SCHEMA = "netto-hz46-pdf-publitas-alignment-review-v1"
IMAGE_MANIFEST_SCHEMA = "netto-hz46-publitas-image-retention-review-v1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
SLUG = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class ReviewProjectionError(ValueError):
    pass


def _verified_json(path: Path, digest: str, limit: int) -> dict:
    if type(digest) is not str or HEX.fullmatch(digest) is None:
        raise ReviewProjectionError("missing or malformed SHA256")
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ReviewProjectionError("missing, symlinked, or oversized input")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ReviewProjectionError("input SHA256 mismatch")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewProjectionError("invalid JSON input") from exc
    if not isinstance(value, dict):
        raise ReviewProjectionError("JSON input must be an object")
    return value


def _box(raw: object) -> dict[str, float]:
    if (not isinstance(raw, list) or len(raw) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in raw)):
        raise ReviewProjectionError("invalid Review marker geometry")
    left, top, width, height = map(float, raw)
    if (left < 0 or top < 0 or width <= 0 or height <= 0
            or left + width > 1.000001 or top + height > 1.000001):
        raise ReviewProjectionError("out-of-page Review marker geometry")
    return {
        "left": round(left, 6), "top": round(top, 6),
        "width": round(width, 6), "height": round(height, 6),
    }


def build_projection(
    markers: dict, alignment: dict, image_manifest: dict, *,
    store_id: str, group: str, slug: str,
    review_markers_sha256: str, alignment_review_sha256: str,
    image_manifest_sha256: str,
) -> dict:
    if (type(store_id) is not str or not store_id.isdigit() or not 1 <= len(store_id) <= 20
            or type(group) is not str or SLUG.fullmatch(group) is None
            or type(slug) is not str or SLUG.fullmatch(slug) is None):
        raise ReviewProjectionError("invalid projection identity")
    if any(type(value) is not str or HEX.fullmatch(value) is None for value in (
        review_markers_sha256, alignment_review_sha256, image_manifest_sha256
    )):
        raise ReviewProjectionError("invalid source digest")

    if (markers.get("format") != MARKER_FORMAT
            or markers.get("publication_page_alignment") != "NOT_VERIFIED"
            or markers.get("retailer_store_identity") != "NOT_VERIFIED"
            or markers.get("offer_identity") != "NOT_VERIFIED"
            or markers.get("automatic_offer_links") != 0):
        raise ReviewProjectionError("markers are not fail-closed Review evidence")
    pdf_sha = markers.get("pdf_sha256")
    page_count = markers.get("page_count")
    marker_pages = markers.get("pages")
    candidate_count = markers.get("candidate_count")
    if (type(pdf_sha) is not str or HEX.fullmatch(pdf_sha) is None
            or type(page_count) is not int or not 1 <= page_count <= 300
            or not isinstance(marker_pages, list) or len(marker_pages) != page_count
            or type(candidate_count) is not int or candidate_count < 0):
        raise ReviewProjectionError("invalid marker manifest shape")

    inputs = alignment.get("inputs")
    result = alignment.get("result")
    pairs = alignment.get("pairs")
    if (alignment.get("schema") != ALIGNMENT_SCHEMA or alignment.get("status") != "REVIEW_ONLY"
            or not isinstance(inputs, dict) or not isinstance(result, dict)
            or not isinstance(pairs, list) or len(pairs) != page_count):
        raise ReviewProjectionError("invalid alignment receipt")
    publication_sha = inputs.get("publication_sha256")
    if (inputs.get("pdf_sha256") != pdf_sha
            or inputs.get("image_manifest_sha256") != image_manifest_sha256
            or inputs.get("publication_page_count") != page_count
            or type(publication_sha) is not str or HEX.fullmatch(publication_sha) is None
            or result.get("same_ordinal_best_matches") != page_count
            or result.get("reverse_best_matches") != page_count
            or result.get("row_best_same_ordinal_80_of_80") is not True
            or result.get("column_best_same_ordinal_80_of_80") is not True
            or result.get("row_best_is_bijection") is not True
            or result.get("mismatch_count") != 0):
        raise ReviewProjectionError("alignment is not exact one-to-one Review evidence")
    for index, pair in enumerate(pairs, 1):
        if (not isinstance(pair, dict)
                or pair.get("publitas_ordinal") != index
                or pair.get("best_pdf_page") != index
                or pair.get("same_ordinal") is not True
                or pair.get("reverse_best") is not True):
            raise ReviewProjectionError("alignment pair is not exact same-ordinal")

    if (image_manifest.get("schema") != IMAGE_MANIFEST_SCHEMA
            or image_manifest.get("publication_sha256") != publication_sha
            or image_manifest.get("pdf_sha256") != pdf_sha
            or image_manifest.get("page_count") != page_count):
        raise ReviewProjectionError("image manifest identity mismatch")
    image_pages = image_manifest.get("pages")
    if not isinstance(image_pages, list) or len(image_pages) != page_count:
        raise ReviewProjectionError("incomplete image manifest")
    page_ids: list[str] = []
    for index, row in enumerate(image_pages, 1):
        page_id = row.get("page_path") if isinstance(row, dict) else None
        if (not isinstance(row, dict) or row.get("ordinal") != index
                or type(page_id) is not str or not page_id.startswith("/")
                or page_id.startswith("//") or ".." in page_id.split("/")
                or len(page_id) > 300):
            raise ReviewProjectionError("invalid image-manifest page identity")
        page_ids.append(page_id)
    if len(set(page_ids)) != page_count:
        raise ReviewProjectionError("duplicate publication page identity")

    projected_pages = []
    seen_candidates: set[str] = set()
    total = 0
    for index, (page, page_id) in enumerate(zip(marker_pages, page_ids), 1):
        if not isinstance(page, dict) or page.get("pdf_page_number") != index:
            raise ReviewProjectionError("marker page order mismatch")
        rows = page.get("candidates")
        if not isinstance(rows, list):
            raise ReviewProjectionError("marker candidates missing")
        candidates = []
        page_source_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ReviewProjectionError("malformed marker candidate")
            source_candidate_id = row.get("candidate_id")
            if (type(source_candidate_id) is not str or not source_candidate_id
                    or len(source_candidate_id) > 150
                    or source_candidate_id in page_source_ids):
                raise ReviewProjectionError("duplicate or invalid page-local candidate identity")
            candidate_id = f"p{index:03d}-{source_candidate_id}"
            title = row.get("candidate_text_unverified")
            prices = row.get("printed_normal_price_candidates_unverified")
            reasons = row.get("review_reasons")
            if (len(candidate_id) > 160
                    or candidate_id in seen_candidates
                    or row.get("marker_basis") != "observed_pdf_price_group_only"
                    or row.get("state") != "REVIEW_ONLY"
                    or row.get("hermes_offer_link") is not None
                    or row.get("verified_product_identity") is not None):
                raise ReviewProjectionError("candidate is not fail-closed Review evidence")
            if title is not None and (type(title) is not str or len(title) > 1200):
                raise ReviewProjectionError("invalid unverified candidate text")
            if (not isinstance(prices, list)
                    or any(type(value) is not str or len(value) > 30 for value in prices)
                    or not isinstance(reasons, list) or not reasons
                    or any(type(value) is not str or len(value) > 140 for value in reasons)):
                raise ReviewProjectionError("invalid Review candidate metadata")
            page_source_ids.add(source_candidate_id)
            seen_candidates.add(candidate_id)
            candidates.append({
                "candidate_id": candidate_id,
                "source_candidate_id": source_candidate_id,
                "rectangle": _box(row.get("marker_bbox")),
                "candidate_text_unverified": title,
                "printed_normal_price_candidates_unverified": prices,
                "review_reasons": reasons,
                "state": "REVIEW_ONLY",
                "source": "pdf_review_only",
                "hermes_offer_link": None,
                "verified_product_identity": None,
            })
        total += len(candidates)
        projected_pages.append({
            "publication_page_number": index,
            "publication_page_identifier": page_id,
            "pdf_page_number": index,
            "candidates": candidates,
        })
    if total != candidate_count or total != len(seen_candidates):
        raise ReviewProjectionError("candidate count mismatch")

    return {
        "format": FORMAT,
        "state": "REVIEW_ONLY",
        "store_id": store_id,
        "group": group,
        "slug": slug,
        "pdf_sha256": pdf_sha,
        "publication_sha256": publication_sha,
        "image_manifest_sha256": image_manifest_sha256,
        "alignment_review_sha256": alignment_review_sha256,
        "review_markers_sha256": review_markers_sha256,
        "page_count": page_count,
        "candidate_count": candidate_count,
        "automatic_offer_links": 0,
        "verified_product_identities": 0,
        "pages": projected_pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-markers", type=Path, required=True)
    parser.add_argument("--review-markers-sha256", required=True)
    parser.add_argument("--alignment-review", type=Path, required=True)
    parser.add_argument("--alignment-review-sha256", required=True)
    parser.add_argument("--image-manifest", type=Path, required=True)
    parser.add_argument("--image-manifest-sha256", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ReviewProjectionError("will not overwrite previous Review projection")
    markers = _verified_json(args.review_markers, args.review_markers_sha256, 8 * 1024 * 1024)
    alignment = _verified_json(args.alignment_review, args.alignment_review_sha256, 8 * 1024 * 1024)
    image_manifest = _verified_json(args.image_manifest, args.image_manifest_sha256, 2 * 1024 * 1024)
    result = build_projection(
        markers, alignment, image_manifest,
        store_id=args.store_id, group=args.group, slug=args.slug,
        review_markers_sha256=args.review_markers_sha256,
        alignment_review_sha256=args.alignment_review_sha256,
        image_manifest_sha256=args.image_manifest_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({
        "pdf_sha256": result["pdf_sha256"],
        "publication_sha256": result["publication_sha256"],
        "page_count": result["page_count"],
        "candidate_count": result["candidate_count"],
        "automatic_offer_links": result["automatic_offer_links"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
