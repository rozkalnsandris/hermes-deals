#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

STRATEGY = "netto_heldout_independent_source_truth_ledger_v1"
RECEIPT_STRATEGY = "netto_heldout_completed_source_truth_receipt_v1"
CAMPAIGN = "hz33_hasb"
STORE = "5659"
SCOPE = "family_primary_netto"
VALID_FROM = "2026-08-10"
VALID_UNTIL = "2026-08-15"
SOURCE_SHA = "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb"
PDF_SHA = "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba"
FREEZE_SHA = "38bb9445ad5f2c3cc0159bd4332a4138f1d81cab03591de0542825b3f88db087"
PACK_MANIFEST_SHA = "e47e1acc337f55dcdbbbfbbb5c200b3c100427ee5e022ad7d0e5e947e2f7274c"
SUPERSEDED_BLANK_SHA = "bc7170d05f075bcd7d90d12952b5811b14a51e69da60304337fcb4aeec557f55"
EXPECTED_GZIP_SHA = "06ccb28e632d8eb6604741b58083a4dd8b45e0c24f8b945b87cd46ff405fbfaf"
EXPECTED_LEDGER_SHA = "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6"
EXPECTED_PAGES = 77
EXPECTED_REGIONS = 341
EXPECTED_IN_SCOPE = 309
EXPECTED_EXCLUDED = 32
EXPECTED_PARTIAL = 9

SOURCE_SCOPES = {"in_scope", "excluded_non_target"}
BOUNDARY_STATES = {"clear_single_card", "partial_single_card"}
CONFIDENCES = {"high", "medium", "low"}
PREDICTION_FIELDS = {
    "ownership_class",
    "single_source",
    "mixed_source",
    "excluded_control",
    "parser_identity",
    "prediction",
    "predictions",
    "selected_group",
    "auto_eligible",
    "promotion_ready",
}


class CompletedSourceTruthError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_payload(path: Path) -> tuple[dict[str, Any], bytes, bytes]:
    if path.is_symlink() or not path.is_file():
        raise CompletedSourceTruthError("truth payload must be a regular non-symlink file")
    try:
        encoded = path.read_text(encoding="ascii").strip()
        compressed = base64.b64decode(encoded, validate=True)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CompletedSourceTruthError("truth payload is not canonical base64") from exc
    if sha256_bytes(compressed) != EXPECTED_GZIP_SHA:
        raise CompletedSourceTruthError("compressed truth payload SHA mismatch")
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise CompletedSourceTruthError("truth payload gzip is invalid") from exc
    if sha256_bytes(raw) != EXPECTED_LEDGER_SHA:
        raise CompletedSourceTruthError("completed source truth SHA mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CompletedSourceTruthError("completed source truth JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise CompletedSourceTruthError("completed source truth must be a JSON object")
    return payload, compressed, raw


def _rect(row: dict[str, Any], width: float, height: float) -> tuple[float, float, float, float]:
    rect = row.get("rect_points")
    if not isinstance(rect, list) or len(rect) != 4:
        raise CompletedSourceTruthError("source region rect_points must contain four values")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in rect):
        raise CompletedSourceTruthError("source region rectangle must be numeric")
    x0, y0, x1, y1 = (float(value) for value in rect)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise CompletedSourceTruthError("source region rectangle must be finite")
    if not (0.0 <= x0 < x1 <= width and 0.0 <= y0 < y1 <= height):
        raise CompletedSourceTruthError("source region rectangle is outside page bounds")
    return x0, y0, x1, y1


def _positive_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _expected_top_level(payload: dict[str, Any]) -> None:
    checks = {
        "schema_version": 1,
        "strategy": STRATEGY,
        "campaign_key": CAMPAIGN,
        "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
        "store_external_id": STORE,
        "scope": SCOPE,
        "source_sha256": SOURCE_SHA,
        "source_pdf_sha256": PDF_SHA,
        "freeze_manifest_sha256": FREEZE_SHA,
        "review_pack_manifest_sha256": PACK_MANIFEST_SHA,
        "supersedes_blank_ledger_sha256": SUPERSEDED_BLANK_SHA,
        "coordinate_space": "unrotated_page_points",
        "page_count": EXPECTED_PAGES,
        "truth_unit": "independent_source_region",
        "review_state": "completed_independent_source_truth_before_prediction_adjudication",
        "parser_predictions_included": False,
        "expected_truth_included": False,
        "adjudication_started": False,
        "source_scope_classes": ["in_scope", "excluded_non_target"],
        "boundary_states": ["clear_single_card", "partial_single_card"],
    }
    for key, expected in checks.items():
        if payload.get(key) != expected:
            raise CompletedSourceTruthError(f"top-level contract mismatch: {key}")
    process = payload.get("reviewer_process")
    if not isinstance(process, dict):
        raise CompletedSourceTruthError("reviewer_process is missing")
    if process.get("frozen_predictions_opened") is not False:
        raise CompletedSourceTruthError("source truth was exposed to frozen predictions")
    if process.get("adjudication_started") is not False:
        raise CompletedSourceTruthError("source truth was exposed to adjudication")
    if process.get("review_order") != "pages_001_through_077_sequential":
        raise CompletedSourceTruthError("review order contract mismatch")
    derivation = payload.get("prediction_ownership_derivation")
    if not isinstance(derivation, dict):
        raise CompletedSourceTruthError("deferred prediction ownership derivation is missing")
    if derivation.get("performed_during_source_review") is not False:
        raise CompletedSourceTruthError("prediction ownership was derived during source review")
    if derivation.get("allowed_only_after_completed_truth_sha_is_frozen") is not True:
        raise CompletedSourceTruthError("prediction ownership freeze gate is missing")


def validate_payload(payload: dict[str, Any]) -> dict[str, int]:
    _expected_top_level(payload)
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != EXPECTED_PAGES:
        raise CompletedSourceTruthError("completed source truth must contain exactly 77 pages")

    ids: set[str] = set()
    scope_counts: Counter[str] = Counter()
    boundary_counts: Counter[str] = Counter()
    total = 0

    for expected_page_number, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page_number") != expected_page_number:
            raise CompletedSourceTruthError("page numbers must be exact sequential 1..77")
        width = page.get("page_width_points")
        height = page.get("page_height_points")
        if (
            isinstance(width, bool) or isinstance(height, bool)
            or not isinstance(width, (int, float)) or not isinstance(height, (int, float))
            or not math.isfinite(float(width)) or not math.isfinite(float(height))
            or float(width) <= 0.0 or float(height) <= 0.0
        ):
            raise CompletedSourceTruthError("page dimensions are invalid")
        rows = page.get("source_regions")
        if not isinstance(rows, list) or not rows:
            raise CompletedSourceTruthError(f"page {expected_page_number} has no independent source regions")

        page_rects: list[tuple[str, tuple[float, float, float, float]]] = []
        for expected_region_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise CompletedSourceTruthError("source region must be an object")
            forbidden = PREDICTION_FIELDS.intersection(row)
            if forbidden:
                raise CompletedSourceTruthError(f"prediction fields leaked into source truth: {sorted(forbidden)}")
            region_id = row.get("source_region_id")
            expected_id = f"p{expected_page_number:03d}-r{expected_region_number:03d}"
            if region_id != expected_id or not re.fullmatch(r"p\d{3}-r\d{3}", str(region_id)):
                raise CompletedSourceTruthError("source region IDs are not deterministic")
            if region_id in ids:
                raise CompletedSourceTruthError("source region IDs are not unique")
            ids.add(region_id)

            scope = row.get("scope_classification")
            boundary = row.get("boundary_state")
            confidence = row.get("reviewer_confidence")
            if scope not in SOURCE_SCOPES:
                raise CompletedSourceTruthError("invalid source scope classification")
            if boundary not in BOUNDARY_STATES:
                raise CompletedSourceTruthError("invalid source boundary state")
            if confidence not in CONFIDENCES:
                raise CompletedSourceTruthError("invalid reviewer confidence")
            label = row.get("observed_label")
            note = row.get("reviewer_note")
            if label is not None and not isinstance(label, str):
                raise CompletedSourceTruthError("observed_label must be string or null")
            if note is not None and not isinstance(note, str):
                raise CompletedSourceTruthError("reviewer_note must be string or null")

            rect = _rect(row, float(width), float(height))
            for other_id, other_rect in page_rects:
                if _positive_overlap(rect, other_rect):
                    raise CompletedSourceTruthError(
                        f"source truth rectangles overlap: {region_id} and {other_id}"
                    )
            page_rects.append((region_id, rect))
            scope_counts[scope] += 1
            boundary_counts[boundary] += 1
            total += 1

    if total != EXPECTED_REGIONS:
        raise CompletedSourceTruthError("source region count mismatch")
    if scope_counts != Counter({"in_scope": EXPECTED_IN_SCOPE, "excluded_non_target": EXPECTED_EXCLUDED}):
        raise CompletedSourceTruthError("source scope distribution mismatch")
    if boundary_counts["partial_single_card"] != EXPECTED_PARTIAL:
        raise CompletedSourceTruthError("partial boundary count mismatch")

    return {
        "page_count": len(pages),
        "source_region_count": total,
        "in_scope_region_count": scope_counts["in_scope"],
        "excluded_non_target_region_count": scope_counts["excluded_non_target"],
        "partial_single_card_count": boundary_counts["partial_single_card"],
    }


def build_receipt(summary: dict[str, int]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "strategy": RECEIPT_STRATEGY,
        "campaign_key": CAMPAIGN,
        "completed_source_truth_sha256": EXPECTED_LEDGER_SHA,
        "compressed_payload_sha256": EXPECTED_GZIP_SHA,
        "review_pack_manifest_sha256": PACK_MANIFEST_SHA,
        "source_sha256": SOURCE_SHA,
        "source_pdf_sha256": PDF_SHA,
        "freeze_manifest_sha256": FREEZE_SHA,
        **summary,
        "frozen_predictions_opened": False,
        "adjudication_started": False,
        "review_only": True,
        "promotion_ready": False,
    }


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def validate_file(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, _, _ = _load_payload(path)
    summary = validate_payload(payload)
    return payload, build_receipt(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the frozen hz33 completed independent source truth.")
    parser.add_argument("payload", type=Path)
    parser.add_argument("--write-receipt", type=Path)
    args = parser.parse_args()
    _, receipt = validate_file(args.payload)
    encoded = receipt_bytes(receipt)
    if args.write_receipt:
        if args.write_receipt.exists() or args.write_receipt.is_symlink():
            raise CompletedSourceTruthError("receipt output must be create-only")
        args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.write_receipt.write_bytes(encoded)
    print(json.dumps({**receipt, "receipt_sha256": sha256_bytes(encoded)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
