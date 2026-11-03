#!/usr/bin/env python3
"""Offline PDF price-group markers for Review, never product/offer links.

The source PDF, its pages and identities are NOT automatically those of the
installed Netto Publitas viewer. No collector, network or database access.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path

from netto_visual_geometry_shadow import analyze_layout, extract_layout_from_pdf

FORMAT = "hermes.netto.pdf_review_markers.v1"


def _relative_box(raw: dict, width: float, height: float) -> list[float]:
    if not isinstance(raw, dict) or any(
        type(raw.get(name)) not in (int, float)
        for name in ("x0", "y0", "x1", "y1")
    ):
        raise ValueError("missing or nonnumeric PDF geometry")
    x0, y0, x1, y1 = (float(raw[name]) for name in ("x0", "y0", "x1", "y1"))
    if (not all(math.isfinite(value) for value in (x0, y0, x1, y1, width, height))
            or not (1 < width <= 5000 and 1 < height <= 5000)
            or not (0 <= x0 < x1 <= width + .001 and 0 <= y0 < y1 <= height + .001)):
        raise ValueError("out-of-page or unsafe geometry")
    return [
        round(x0 / width, 6), round(y0 / height, 6),
        round((x1 - x0) / width, 6), round((y1 - y0) / height, 6),
    ]


def review_page(analysis: dict, page_number: int) -> dict:
    """Only observable price-label boxes; never guessed product-card outlines."""
    if not isinstance(analysis, dict) or any(
        analysis.get(key) is not expected for key, expected in (
            ("shadow_only", True), ("production_eligible", False),
            ("promotion_ready", False),
        )
    ):
        raise ValueError("analysis is not fail-closed")
    page = analysis.get("page")
    if (not isinstance(page, dict) or page.get("page_number") != page_number
            or type(page.get("rotation")) is not int or page["rotation"] != 0):
        raise ValueError("untrusted or rotated page")
    width = float(page.get("width_points") or 0)
    height = float(page.get("height_points") or 0)
    groups = analysis.get("groups")
    if not isinstance(groups, list):
        raise ValueError("missing review groups")
    seen = set()
    markers = []
    for group in groups:
        if not isinstance(group, dict) or any(
            group.get(key) is not expected for key, expected in (
                ("shadow_only", True), ("production_eligible", False),
                ("promotion_ready", False), ("route", "review_required"),
            )
        ):
            raise ValueError("unexpected promotable or malformed group")
        gid = group.get("group_id")
        if not isinstance(gid, str) or not gid or gid in seen:
            raise ValueError("duplicate group identity")
        seen.add(gid)
        bbox = _relative_box(group.get("bbox"), width, height)
        title = group.get("selected_title")
        prices = group.get("normal_price_candidates")
        reasons = group.get("reasons")
        if (title is not None and (not isinstance(title, str) or len(title) > 1200)):
            raise ValueError("unbounded title candidate")
        if (not isinstance(prices, list) or
                any(not isinstance(p, str) or len(p) > 30 for p in prices)):
            raise ValueError("malformed printed price candidates")
        if (not isinstance(reasons, list) or not reasons or
                any(not isinstance(reason, str) or len(reason) > 140 for reason in reasons)):
            raise ValueError("missing review reason")
        markers.append({
            "candidate_id": gid,
            "pdf_page_number": page_number,
            "marker_bbox": bbox,
            "marker_basis": "observed_pdf_price_group_only",
            "candidate_text_unverified": title,
            "printed_normal_price_candidates_unverified": prices,
            "review_reasons": reasons,
            "state": "REVIEW_ONLY",
            "hermes_offer_link": None,
            "verified_product_identity": None,
        })
    return {"pdf_page_number": page_number, "candidates": markers}


def build_manifest(pdf: Path, *, expected_pages: int | None = None) -> dict:
    import fitz

    pdf = pdf.resolve(strict=True)
    if not pdf.is_file() or not 0 < pdf.stat().st_size <= 150 * 1024 * 1024:
        raise ValueError("invalid PDF file")
    digest = sha256(pdf.read_bytes()).hexdigest()
    with fitz.open(pdf) as document:
        count = document.page_count
        if document.needs_pass or not 1 <= count <= 300:
            raise ValueError("unusable or oversized PDF")
    if expected_pages is not None and count != expected_pages:
        raise ValueError(f"PDF page count differs: expected {expected_pages}, got {count}")
    pages = [
        review_page(analyze_layout(extract_layout_from_pdf(pdf, n)), n)
        for n in range(1, count + 1)
    ]
    return {
        "format": FORMAT,
        "pdf_sha256": digest,
        "page_count": count,
        "publication_page_alignment": "NOT_VERIFIED",
        "retailer_store_identity": "NOT_VERIFIED",
        "offer_identity": "NOT_VERIFIED",
        "automatic_offer_links": 0,
        "candidate_count": sum(len(row["candidates"]) for row in pages),
        "pages": pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--expected-pages", type=int, default=None)
    args = parser.parse_args()
    dest = args.output_json.resolve()
    if dest.exists():
        raise ValueError("will not overwrite previous review evidence")
    result = build_manifest(args.source_pdf, expected_pages=args.expected_pages)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "pdf_sha256", "page_count", "candidate_count", "automatic_offer_links"
    )}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
