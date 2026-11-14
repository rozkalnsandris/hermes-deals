#!/usr/bin/env python3
"""Diagnose Netto HZ46 price/text/image grouping without changing selection.

This harness is intentionally REVIEW_ONLY. It preserves the current parser
output, exposes alternative source-native text/image evidence for each primary
price anchor, and evaluates accepted product-card candidates against a
human-reviewed golden fixture. It never creates product identity or offer links.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
from netto_booklet_recognition_inference import (  # noqa: E402
    InferenceRunnerError,
    NATIVE_PRODUCT_IMAGE_MAX_GAP,
    NATIVE_PRODUCT_IMAGE_OWNER_RADIUS,
    NATIVE_PRICE_GROUP_RADIUS,
    _bbox_distance,
    _bbox_gap_distance,
    _product_image_candidate,
    _product_text_token,
    _read_pdf,
    native_page_structure,
)


FORMAT = "hermes.netto.hz46_grouping_diagnostics.v1"
GOLDEN_STRATEGY = "netto_hz46_pages_3_5_offer_golden_v1"


class GroupingDiagnosticsError(ValueError):
    pass


def _normalized_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _normalized_price(value: object) -> str | None:
    match = re.search(r"(?<!\d)(\d{1,3})[.,](\d{2})(?!\d)", str(value or ""))
    if match is None:
        return None
    return f"{int(match.group(1))}.{match.group(2)}"


def _bbox_union(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        raise GroupingDiagnosticsError("cannot union empty diagnostic rectangles")
    x0 = min(float(box[0]) for box in boxes)
    y0 = min(float(box[1]) for box in boxes)
    x1 = max(float(box[0]) + float(box[2]) for box in boxes)
    y1 = max(float(box[1]) + float(box[3]) for box in boxes)
    return [round(x0, 6), round(y0, 6), round(x1 - x0, 6), round(y1 - y0, 6)]


def _axis_overlap_ratio(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = map(float, a)
    bx, by, bw, bh = map(float, b)
    x_overlap = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    y_overlap = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    x_ratio = x_overlap / min(aw, bw) if min(aw, bw) > 0 else 0.0
    y_ratio = y_overlap / min(ah, bh) if min(ah, bh) > 0 else 0.0
    return round(max(x_ratio, y_ratio), 6)


def _text_alternatives(native: dict, anchor: dict) -> list[dict]:
    rows = native.get("text_regions")
    if not isinstance(rows, list):
        raise GroupingDiagnosticsError("native text regions are missing")

    by_block: dict[int, list[dict]] = {}
    for row in rows:
        if row.get("region_id") == anchor.get("region_id"):
            continue
        block_no = row.get("block_no")
        if type(block_no) is not int:
            raise GroupingDiagnosticsError("native text block number is malformed")
        by_block.setdefault(block_no, []).append(row)

    alternatives = []
    for block_no, block_rows in by_block.items():
        ordered = sorted(
            block_rows,
            key=lambda row: (
                int(row.get("line_no") or 0),
                int(row.get("word_no") or 0),
                row["bbox"][1],
                row["bbox"][0],
            ),
        )
        bbox = _bbox_union([row["bbox"] for row in ordered])
        gap = _bbox_gap_distance(bbox, anchor["bbox"])
        distance = _bbox_distance(bbox, anchor["bbox"])
        if gap > NATIVE_PRICE_GROUP_RADIUS and distance > NATIVE_PRICE_GROUP_RADIUS:
            continue

        text = " ".join(str(row.get("text") or "") for row in ordered).strip()
        product_like = any(_product_text_token(row.get("text")) for row in ordered)
        alternatives.append(
            {
                "block_no": block_no,
                "text": text,
                "region_ids": [row["region_id"] for row in ordered],
                "bbox": bbox,
                "gap_to_price": round(gap, 6),
                "center_distance_to_price": round(distance, 6),
                "axis_overlap_with_price": _axis_overlap_ratio(bbox, anchor["bbox"]),
                "product_text_signal": bool(product_like),
            }
        )

    return sorted(
        alternatives,
        key=lambda row: (
            not row["product_text_signal"],
            row["gap_to_price"],
            row["center_distance_to_price"],
            row["block_no"],
        ),
    )


def _image_alternatives(native: dict, anchor: dict) -> list[dict]:
    rows = native.get("image_regions")
    if not isinstance(rows, list):
        raise GroupingDiagnosticsError("native image regions are missing")

    alternatives = []
    for row in rows:
        if not _product_image_candidate(row):
            continue
        gap = _bbox_gap_distance(row["bbox"], anchor["bbox"])
        distance = _bbox_distance(row["bbox"], anchor["bbox"])
        alternatives.append(
            {
                "region_id": row["region_id"],
                "bbox": row["bbox"],
                "pixel_width": int(row.get("pixel_width") or 0),
                "pixel_height": int(row.get("pixel_height") or 0),
                "xref": int(row.get("xref") or 0),
                "gap_to_price": round(gap, 6),
                "center_distance_to_price": round(distance, 6),
                "within_current_gap_limit": gap <= NATIVE_PRODUCT_IMAGE_MAX_GAP,
                "within_current_owner_radius": (
                    distance <= NATIVE_PRODUCT_IMAGE_OWNER_RADIUS
                ),
            }
        )
    return sorted(
        alternatives,
        key=lambda row: (
            row["gap_to_price"],
            row["center_distance_to_price"],
            row["region_id"],
        ),
    )


def diagnose_page(native: dict, page_number: int) -> dict:
    if type(page_number) is not int or page_number < 1:
        raise GroupingDiagnosticsError("invalid page number")
    prices = native.get("primary_price_candidates")
    cards = native.get("product_card_candidates")
    excluded = native.get("date_price_region_ids_excluded")
    if not isinstance(prices, list) or not isinstance(cards, list):
        raise GroupingDiagnosticsError("native price/card candidates are missing")
    if not isinstance(excluded, list):
        raise GroupingDiagnosticsError("native date-price exclusions are missing")

    cards_by_price: dict[str, list[dict]] = {}
    for card in cards:
        price_id = card.get("price_region_id")
        if isinstance(price_id, str):
            cards_by_price.setdefault(price_id, []).append(card)

    card_trace = native.get("product_card_selection_trace")
    if card_trace is not None and (
        not isinstance(card_trace, dict)
        or not isinstance(card_trace.get("by_price"), dict)
    ):
        raise GroupingDiagnosticsError("malformed optional card selection trace")

    anchors = []
    for anchor in prices:
        price_id = anchor.get("region_id")
        if not isinstance(price_id, str) or not price_id:
            raise GroupingDiagnosticsError("primary price region id is malformed")
        text_alternatives = _text_alternatives(native, anchor)
        image_alternatives = _image_alternatives(native, anchor)
        accepted = cards_by_price.get(price_id, [])

        reasons = []
        if price_id in excluded:
            status = "not_product_date_price"
            reasons.append("date_price_excluded")
        elif len(accepted) > 1:
            status = "ambiguous"
            reasons.append("multiple_current_cards_for_price")
        elif len(accepted) == 1:
            status = "accepted"
        elif not any(row["product_text_signal"] for row in text_alternatives):
            status = "missing_evidence"
            reasons.append("no_product_text_alternative")
        elif not any(
            row["within_current_gap_limit"] and row["within_current_owner_radius"]
            for row in image_alternatives
        ):
            status = "missing_evidence"
            reasons.append("no_product_image_alternative_within_current_limits")
        else:
            status = "rejected_or_ambiguous"
            reasons.append("evidence_exists_but_current_card_not_emitted")

        detail = {
                "price_region_id": price_id,
                "price_text": str(anchor.get("text") or ""),
                "price_bbox": anchor.get("bbox"),
                "status": status,
                "rejection_reasons": reasons,
                "current_card_candidate_ids": [
                    str(row.get("candidate_id") or "") for row in accepted
                ],
                "text_alternatives": text_alternatives,
                "image_alternatives": image_alternatives,
            }
        if card_trace is not None:
            by_price = card_trace["by_price"]
            if price_id not in by_price:
                raise GroupingDiagnosticsError("missing traced price anchor")
            detail["card_selection_trace"] = by_price[price_id]
        anchors.append(detail)

    return {
        "pdf_page_number": page_number,
        "primary_price_anchor_count": len(prices),
        "current_product_card_count": len(cards),
        "anchors": anchors,
    }


def _validate_golden(golden: dict) -> None:
    if (
        not isinstance(golden, dict)
        or golden.get("schema_version") != 1
        or golden.get("strategy") != GOLDEN_STRATEGY
    ):
        raise GroupingDiagnosticsError("unsupported HZ46 golden fixture")
    safety = golden.get("safety")
    if not isinstance(safety, dict) or safety.get("review_only") is not True:
        raise GroupingDiagnosticsError("golden fixture is not REVIEW_ONLY")
    if (
        safety.get("automatic_offer_links") != 0
        or safety.get("verified_product_identities") != 0
        or safety.get("product_boundaries_proven") != 0
        or safety.get("automatic_publish_enabled") is not False
    ):
        raise GroupingDiagnosticsError("golden fixture crosses identity boundary")


def _evaluate_candidate_family(
    candidates: list[dict],
    golden_page: dict,
    *,
    family: str,
) -> dict:
    outcomes = []
    resolved_slots = 0
    matched_title_slots = 0
    matched_title_price_slots = 0
    ambiguous_slots = 0

    for offer in golden_page.get("offers") or []:
        golden_id = offer.get("golden_id")
        title = offer.get("expected_title")
        expected_price = offer.get("expected_primary_price")
        tokens = offer.get("required_title_tokens")
        if not isinstance(golden_id, str) or not isinstance(tokens, list):
            raise GroupingDiagnosticsError("malformed golden offer")

        if title is None:
            outcomes.append(
                {
                    "golden_id": golden_id,
                    "status": "truth_unresolved",
                    "candidate_ids": [],
                }
            )
            continue

        resolved_slots += 1
        normalized_tokens = [_normalized_text(token) for token in tokens]
        title_matches = []
        exact_matches = []
        for candidate in candidates:
            if candidate.get("assignment_state") == "UNRESOLVED":
                continue
            normalized_candidate = _normalized_text(candidate.get("product_text"))
            if not all(
                token and token in normalized_candidate
                for token in normalized_tokens
            ):
                continue
            title_matches.append(candidate)
            if expected_price is None:
                exact_matches.append(candidate)
            elif _normalized_price(candidate.get("price_text")) == expected_price:
                exact_matches.append(candidate)

        if len(title_matches) == 1:
            matched_title_slots += 1
        if len(exact_matches) == 1:
            matched_title_price_slots += 1

        if len(exact_matches) > 1 or len(title_matches) > 1:
            status = "ambiguous"
            ambiguous_slots += 1
            chosen = exact_matches or title_matches
        elif len(exact_matches) == 1:
            status = "matched"
            chosen = exact_matches
        elif title_matches:
            status = "price_mismatch"
            chosen = title_matches
        else:
            status = "missing"
            chosen = []

        outcomes.append(
            {
                "golden_id": golden_id,
                "status": status,
                "candidate_ids": [
                    str(row.get("candidate_id") or "") for row in chosen
                ],
            }
        )

    return {
        "family": family,
        "candidate_count": len(candidates),
        "resolved_truth_slots": resolved_slots,
        "matched_title_slots": matched_title_slots,
        "matched_title_price_slots": matched_title_price_slots,
        "ambiguous_slots": ambiguous_slots,
        "outcomes": outcomes,
    }


def evaluate_page(native: dict, golden_page: dict) -> dict:
    cards = native.get("product_card_candidates")
    price_text = native.get("price_text_candidates")
    if not isinstance(cards, list):
        raise GroupingDiagnosticsError("native product-card candidates are missing")
    if not isinstance(price_text, list):
        raise GroupingDiagnosticsError("native price-text candidates are missing")

    card_eval = _evaluate_candidate_family(
        cards,
        golden_page,
        family="product_card",
    )
    price_text_eval = _evaluate_candidate_family(
        price_text,
        golden_page,
        family="price_text",
    )

    return {
        "pdf_page_number": int(golden_page["page_number"]),
        "expected_offer_count": int(golden_page.get("expected_offer_count") or 0),
        "resolved_truth_slots": card_eval["resolved_truth_slots"],
        "current_product_card_count": card_eval["candidate_count"],
        "matched_title_slots": card_eval["matched_title_slots"],
        "matched_title_price_slots": card_eval["matched_title_price_slots"],
        "ambiguous_slots": card_eval["ambiguous_slots"],
        "outcomes": card_eval["outcomes"],
        "price_text_candidate_count": price_text_eval["candidate_count"],
        "price_text_matched_title_slots": price_text_eval["matched_title_slots"],
        "price_text_matched_title_price_slots": (
            price_text_eval["matched_title_price_slots"]
        ),
        "price_text_ambiguous_slots": price_text_eval["ambiguous_slots"],
        "price_text_outcomes": price_text_eval["outcomes"],
    }


def build_report(pdf: Path, golden_path: Path, expected_sha256: str) -> dict:
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    _validate_golden(golden)
    raw = _read_pdf(pdf, expected_sha256)

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for HZ46 grouping diagnostics") from exc

    page_specs = golden.get("pages")
    if not isinstance(page_specs, list) or not page_specs:
        raise GroupingDiagnosticsError("golden pages are missing")

    diagnostics = []
    evaluations = []
    with fitz.open(stream=raw, filetype="pdf") as document:
        publication = golden.get("publication") or {}
        expected_pages = publication.get("page_count")
        if document.page_count != expected_pages:
            raise GroupingDiagnosticsError("PDF page count differs from golden fixture")
        for golden_page in page_specs:
            page_number = int(golden_page["page_number"])
            native = native_page_structure(
                document[page_number - 1], trace_product_cards=True
            )
            diagnostics.append(diagnose_page(native, page_number))
            evaluations.append(evaluate_page(native, golden_page))

    totals = {
        "expected_offer_slots": sum(row["expected_offer_count"] for row in evaluations),
        "resolved_truth_slots": sum(row["resolved_truth_slots"] for row in evaluations),
        "current_product_cards": sum(row["current_product_card_count"] for row in evaluations),
        "matched_title_slots": sum(row["matched_title_slots"] for row in evaluations),
        "matched_title_price_slots": sum(
            row["matched_title_price_slots"] for row in evaluations
        ),
        "ambiguous_slots": sum(row["ambiguous_slots"] for row in evaluations),
        "price_text_candidates": sum(
            row["price_text_candidate_count"] for row in evaluations
        ),
        "price_text_matched_title_slots": sum(
            row["price_text_matched_title_slots"] for row in evaluations
        ),
        "price_text_matched_title_price_slots": sum(
            row["price_text_matched_title_price_slots"] for row in evaluations
        ),
        "price_text_ambiguous_slots": sum(
            row["price_text_ambiguous_slots"] for row in evaluations
        ),
    }

    return {
        "format": FORMAT,
        "pdf_sha256": sha256(raw).hexdigest(),
        "golden_strategy": GOLDEN_STRATEGY,
        "state": "REVIEW_ONLY",
        "automatic_offer_links": 0,
        "verified_product_identities": 0,
        "product_boundaries_proven": 0,
        "totals": totals,
        "evaluations": evaluations,
        "diagnostics": diagnostics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("golden_json", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--pdf-sha256", required=True)
    args = parser.parse_args()

    output = args.output_json.resolve()
    if output.exists() or output.is_symlink():
        raise GroupingDiagnosticsError("will not overwrite previous diagnostics")

    report = build_report(
        args.source_pdf,
        args.golden_json.resolve(strict=True),
        args.pdf_sha256,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(report["totals"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
