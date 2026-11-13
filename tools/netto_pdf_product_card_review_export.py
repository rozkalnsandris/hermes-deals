#!/usr/bin/env python3
"""Export Review-only Netto product-card markers from source-native PDF geometry.

The exporter is offline and deterministic. A marker requires three observed
source elements on the same PDF page: a prominent non-date price token, a
nearby substantive product-text block, and a nearby substantive PDF image.
The resulting rectangle remains REVIEW_ONLY and never creates product identity,
offer ownership, price history, or a Hermes offer link.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from netto_booklet_recognition_inference import (  # noqa: E402
    InferenceRunnerError,
    _read_pdf,
    native_page_structure,
)

FORMAT = "hermes.netto.pdf_product_card_review_markers.v2"
MARKER_BASIS = "observed_pdf_product_card_candidate"
_PRICE = re.compile(r"^(\d{1,3})[.,](\d{2})")


class ProductCardReviewExportError(ValueError):
    pass


def _safe_box(raw: object) -> list[float]:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in raw)
    ):
        raise ProductCardReviewExportError("invalid product-card geometry")
    left, top, width, height = map(float, raw)
    if (
        left < 0
        or top < 0
        or width <= 0
        or height <= 0
        or left + width > 1.000001
        or top + height > 1.000001
    ):
        raise ProductCardReviewExportError("product-card geometry outside page")
    return [round(left, 6), round(top, 6), round(width, 6), round(height, 6)]


def _printed_price(value: object) -> str:
    match = _PRICE.match(str(value or "").replace("€", "").strip().rstrip("*"))
    if match is None:
        raise ProductCardReviewExportError("product-card price is malformed")
    return f"{int(match.group(1))}.{match.group(2)}"


def review_page(native: dict, page_number: int) -> dict:
    if not isinstance(native, dict):
        raise ProductCardReviewExportError("native page evidence is missing")
    rows = native.get("product_card_candidates")
    if not isinstance(rows, list):
        raise ProductCardReviewExportError("product-card candidates are missing")

    candidates = []
    seen: set[str] = set()
    for ordinal, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or row.get("basis") != "native_pdf_product_text_image_price_card_v2"
            or row.get("state") != "REVIEW_ONLY"
            or row.get("product_boundary_proven") is not False
            or row.get("verified_product_identity") is not None
            or row.get("hermes_offer_link") is not None
        ):
            raise ProductCardReviewExportError("product-card candidate is not fail-closed")

        source_id = row.get("candidate_id")
        title = row.get("product_text")
        image_id = row.get("product_image_region_id")
        price_id = row.get("price_region_id")
        reasons = row.get("review_reasons")
        if (
            type(source_id) is not str
            or not source_id
            or source_id in seen
            or type(title) is not str
            or not title.strip()
            or len(title) > 1200
            or type(image_id) is not str
            or not image_id
            or type(price_id) is not str
            or not price_id
            or not isinstance(reasons, list)
            or not reasons
            or any(type(value) is not str or len(value) > 140 for value in reasons)
        ):
            raise ProductCardReviewExportError("malformed product-card candidate metadata")
        seen.add(source_id)

        candidates.append(
            {
                "candidate_id": f"c{ordinal:03d}",
                "source_candidate_id": source_id,
                "source_price_region_id": price_id,
                "source_product_image_region_id": image_id,
                "pdf_page_number": page_number,
                "marker_bbox": _safe_box(row.get("card_bbox")),
                "marker_basis": MARKER_BASIS,
                "candidate_text_unverified": title.strip(),
                "printed_normal_price_candidates_unverified": [
                    _printed_price(row.get("price_text"))
                ],
                "review_reasons": sorted(set(reasons)),
                "state": "REVIEW_ONLY",
                "product_boundary_proven": False,
                "hermes_offer_link": None,
                "verified_product_identity": None,
            }
        )
    return {"pdf_page_number": page_number, "candidates": candidates}


def build_manifest(
    pdf: Path,
    *,
    expected_sha256: str,
    expected_pages: int | None = None,
) -> dict:
    try:
        raw = _read_pdf(pdf, expected_sha256)
    except InferenceRunnerError as exc:
        raise ProductCardReviewExportError(str(exc)) from exc

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for product-card extraction") from exc

    pages = []
    date_excluded = 0
    primary_prices = 0
    with fitz.open(stream=raw, filetype="pdf") as document:
        if document.needs_pass or not 1 <= document.page_count <= 300:
            raise ProductCardReviewExportError("unusable or oversized PDF")
        if expected_pages is not None and document.page_count != expected_pages:
            raise ProductCardReviewExportError(
                f"PDF page count differs: expected {expected_pages}, got {document.page_count}"
            )
        for page_number in range(1, document.page_count + 1):
            native = native_page_structure(document[page_number - 1])
            pages.append(review_page(native, page_number))
            date_excluded += int(native.get("date_price_candidate_count_excluded") or 0)
            primary_prices += int(native.get("primary_price_candidate_count") or 0)

    candidate_count = sum(len(page["candidates"]) for page in pages)
    return {
        "format": FORMAT,
        "pdf_sha256": sha256(raw).hexdigest(),
        "page_count": len(pages),
        "publication_page_alignment": "NOT_VERIFIED",
        "retailer_store_identity": "NOT_VERIFIED",
        "offer_identity": "NOT_VERIFIED",
        "automatic_offer_links": 0,
        "verified_product_identities": 0,
        "product_boundaries_proven": 0,
        "primary_price_candidate_count": primary_prices,
        "date_price_candidate_count_excluded": date_excluded,
        "candidate_count": candidate_count,
        "pages": pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--expected-pages", type=int, default=None)
    args = parser.parse_args()

    dest = args.output_json.resolve()
    if dest.exists() or dest.is_symlink():
        raise ProductCardReviewExportError("will not overwrite previous Review evidence")
    result = build_manifest(
        args.source_pdf,
        expected_sha256=args.pdf_sha256,
        expected_pages=args.expected_pages,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "pdf_sha256": result["pdf_sha256"],
                "page_count": result["page_count"],
                "primary_price_candidate_count": result["primary_price_candidate_count"],
                "date_price_candidate_count_excluded": result[
                    "date_price_candidate_count_excluded"
                ],
                "candidate_count": result["candidate_count"],
                "automatic_offer_links": result["automatic_offer_links"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
