#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping
import zipfile

CAMPAIGN = "hz34_hasb"
STORE = "5659"
SCOPE = "family_primary_netto"
VALID_FROM = "2026-08-17"
VALID_UNTIL = "2026-08-22"
SOURCE_SHA256 = "1fdb1a20b09f9d23663f4ff052fe412591eab799033262447708fd85e4058465"
PDF_SHA256 = "b92d7ace8428d49daf0658d769af88b1b0ef3fcd31e4244a00aeaf0150277169"
FREEZE_MANIFEST_SHA256 = "0ca98977d2870e13a8ec985db6c90258fbe6276dc24737d606b739c6517ae4c8"
REVIEW_PACK_MANIFEST_SHA256 = "eff911a09ef343abda3c6c16922e998b4903ef0ccaa679a1423a83f26ffc43f3"
BLANK_LEDGER_SHA256 = "5e0dcb89d9cd957175e5c4bdcba5de1fb7c8075c1b16db9a139c20052e108d79"
ARTIFACT_SOURCE_RECEIPT_SHA256 = "cc50b5f49dd3f62618556832416dc2f694e023000664bbb145e9b2b3cdb2bad8"
REVIEW_PACK_ARTIFACT_ID = 9737495579
REVIEW_PACK_RUN_ID = 33330445681
REVIEW_PACK_ARTIFACT = "netto-hz34-blind-review-pack-33330445681-1"
REVIEW_PACK_ARTIFACT_DIGEST = "sha256:ba30feab1ed792ed62fc613acc2c1c1b06a43bfaa3754666170a98a4da1e5b32"
EXPECTED_PAGES = 70
STRATEGY = "netto_hz34_independent_source_truth_v1"
RECEIPT_STRATEGY = "netto_hz34_completed_source_truth_receipt_v1"
SOURCE_SCOPES = {"in_scope", "excluded_non_target"}
BOUNDARY_STATES = {"clear_single_card", "partial_single_card"}
CONFIDENCES = {"high", "medium", "low"}
FORBIDDEN_KEYS = {
    "ownership_class", "single_source", "mixed_source", "excluded_control",
    "parser_identity", "prediction", "predictions", "selected_group",
    "auto_eligible", "production_eligible", "promotion_ready",
    "candidate_provenance", "candidate_decision", "threshold",
}


class Hz34CompletedTruthError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise Hz34CompletedTruthError(f"input must be a regular non-symlink file: {path}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Hz34CompletedTruthError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise Hz34CompletedTruthError("JSON root must be an object")
    return payload, raw


def _zip_regular(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return not mode or stat.S_ISREG(mode)


def _validate_zip_name(name: str) -> None:
    pure = PurePosixPath(name)
    if (not name or name.startswith("/") or "\\" in name or pure.as_posix() != name
            or any(part in {"", ".", ".."} for part in pure.parts)):
        raise Hz34CompletedTruthError(f"unsafe review-pack member: {name}")


def _read_exact_member(archive: zipfile.ZipFile, name: str, expected_sha: str) -> bytes:
    try:
        data = archive.read(name)
    except KeyError as exc:
        raise Hz34CompletedTruthError(f"required review-pack member missing: {name}") from exc
    if sha256_bytes(data) != expected_sha:
        raise Hz34CompletedTruthError(f"review-pack member SHA mismatch: {name}")
    return data


def validate_review_pack_zip(path: Path) -> dict[int, tuple[float, float]]:
    if path.is_symlink() or not path.is_file():
        raise Hz34CompletedTruthError("review-pack ZIP must be a regular non-symlink file")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise Hz34CompletedTruthError("duplicate review-pack member")
        for info in infos:
            _validate_zip_name(info.filename)
            if info.is_dir() or not _zip_regular(info):
                raise Hz34CompletedTruthError(f"non-regular review-pack member: {info.filename}")
        manifest_raw = _read_exact_member(archive, "manifest.json", REVIEW_PACK_MANIFEST_SHA256)
        ledger_raw = _read_exact_member(archive, "independent-source-card-review-ledger.json", BLANK_LEDGER_SHA256)
        _read_exact_member(archive, "artifact-source-receipt.json", ARTIFACT_SOURCE_RECEIPT_SHA256)
        manifest = json.loads(manifest_raw)
        ledger = json.loads(ledger_raw)
        expected_manifest = {
            "campaign_key": CAMPAIGN,
            "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
            "store_external_id": STORE,
            "scope": SCOPE,
            "source_sha256": SOURCE_SHA256,
            "source_pdf_sha256": PDF_SHA256,
            "freeze_manifest_sha256": FREEZE_MANIFEST_SHA256,
            "blank_review_ledger_sha256": BLANK_LEDGER_SHA256,
            "coordinate_space": "unrotated_page_points",
            "page_count": EXPECTED_PAGES,
        }
        for key, value in expected_manifest.items():
            if manifest.get(key) != value:
                raise Hz34CompletedTruthError(f"review-pack manifest mismatch: {key}")
        contract = manifest.get("blind_review_contract") or {}
        required_false = (
            "parser_predictions_included", "expected_truth_included", "presegmented_review_units",
            "database_write_performed", "review_write_performed", "deployment_performed",
        )
        if any(contract.get(key) is not False for key in required_false):
            raise Hz34CompletedTruthError("review-pack blind contract mismatch")
        if contract.get("source_pages_only") is not True or contract.get("source_text_only") is not True:
            raise Hz34CompletedTruthError("review-pack source-only contract mismatch")
        pages = ledger.get("pages")
        if not isinstance(pages, list) or len(pages) != EXPECTED_PAGES:
            raise Hz34CompletedTruthError("blank review ledger page count mismatch")
        dimensions: dict[int, tuple[float, float]] = {}
        for expected_number, page in enumerate(pages, start=1):
            if not isinstance(page, dict) or page.get("page_number") != expected_number:
                raise Hz34CompletedTruthError("blank review ledger page sequence mismatch")
            if page.get("source_cards") != []:
                raise Hz34CompletedTruthError("review-pack ledger is not blank")
            width, height = page.get("page_width_points"), page.get("page_height_points")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (width, height)):
                raise Hz34CompletedTruthError("blank review ledger page dimensions are invalid")
            dimensions[expected_number] = (float(width), float(height))
        return dimensions


def _rect(row: Mapping[str, Any], width: float, height: float) -> tuple[float, float, float, float]:
    rect = row.get("rect_points")
    if not isinstance(rect, list) or len(rect) != 4:
        raise Hz34CompletedTruthError("source region rect_points must contain four values")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in rect):
        raise Hz34CompletedTruthError("source region rectangle must be numeric")
    x0, y0, x1, y1 = (float(value) for value in rect)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise Hz34CompletedTruthError("source region rectangle must be finite")
    if not (0.0 <= x0 < x1 <= width and 0.0 <= y0 < y1 <= height):
        raise Hz34CompletedTruthError("source region rectangle is outside page bounds")
    return x0, y0, x1, y1


def _positive_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _reject_prediction_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_KEYS.intersection(value)
        if forbidden:
            raise Hz34CompletedTruthError(f"prediction/candidate fields leaked into truth at {path}: {sorted(forbidden)}")
        for key, child in value.items():
            _reject_prediction_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_prediction_keys(child, path=f"{path}[{index}]")


def validate_truth_payload(payload: dict[str, Any], page_dimensions: Mapping[int, tuple[float, float]]) -> dict[str, Any]:
    _reject_prediction_keys(payload)
    expected = {
        "schema_version": 1,
        "strategy": STRATEGY,
        "campaign_key": CAMPAIGN,
        "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
        "store_external_id": STORE,
        "scope": SCOPE,
        "source_sha256": SOURCE_SHA256,
        "source_pdf_sha256": PDF_SHA256,
        "freeze_manifest_sha256": FREEZE_MANIFEST_SHA256,
        "review_pack_manifest_sha256": REVIEW_PACK_MANIFEST_SHA256,
        "supersedes_blank_ledger_sha256": BLANK_LEDGER_SHA256,
        "coordinate_space": "unrotated_page_points",
        "page_count": EXPECTED_PAGES,
        "review_state": "completed_independent_source_truth_before_prediction_adjudication",
        "truth_unit": "independent_source_region",
        "source_scope_classes": ["in_scope", "excluded_non_target"],
        "boundary_states": ["clear_single_card", "partial_single_card"],
        "parser_predictions_included": False,
        "candidate_provenance_included": False,
        "expected_truth_included": False,
        "adjudication_started": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise Hz34CompletedTruthError(f"completed truth contract mismatch: {key}")
    process = payload.get("reviewer_process")
    if not isinstance(process, dict):
        raise Hz34CompletedTruthError("reviewer_process is missing")
    process_expected = {
        "review_pack_artifact_id": REVIEW_PACK_ARTIFACT_ID,
        "review_pack_workflow_run_id": REVIEW_PACK_RUN_ID,
        "review_pack_artifact": REVIEW_PACK_ARTIFACT,
        "review_pack_artifact_digest": REVIEW_PACK_ARTIFACT_DIGEST,
        "frozen_predictions_opened": False,
        "candidate_provenance_opened": False,
        "adjudication_started": False,
        "review_order": "pages_001_through_070_sequential",
    }
    for key, value in process_expected.items():
        if process.get(key) != value:
            raise Hz34CompletedTruthError(f"reviewer process mismatch: {key}")
    derivation = payload.get("prediction_ownership_derivation")
    if not isinstance(derivation, dict):
        raise Hz34CompletedTruthError("prediction ownership derivation gate is missing")
    if derivation.get("performed_during_source_review") is not False:
        raise Hz34CompletedTruthError("prediction ownership was derived during source review")
    if derivation.get("allowed_only_after_completed_truth_sha_is_frozen") is not True:
        raise Hz34CompletedTruthError("post-freeze ownership gate is missing")
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != EXPECTED_PAGES:
        raise Hz34CompletedTruthError("completed truth must contain exactly 70 pages")
    if set(page_dimensions) != set(range(1, EXPECTED_PAGES + 1)):
        raise Hz34CompletedTruthError("review-pack page-dimension map is incomplete")
    ids: set[str] = set()
    scope_counts: Counter[str] = Counter()
    boundary_counts: Counter[str] = Counter()
    total = empty_pages = 0
    for expected_page, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page_number") != expected_page:
            raise Hz34CompletedTruthError("truth pages must be sequential 1..70")
        expected_width, expected_height = page_dimensions[expected_page]
        width, height = page.get("page_width_points"), page.get("page_height_points")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (width, height)):
            raise Hz34CompletedTruthError("truth page dimensions are invalid")
        if float(width) != expected_width or float(height) != expected_height:
            raise Hz34CompletedTruthError("truth page dimensions differ from reviewer pack")
        if page.get("review_complete") is not True:
            raise Hz34CompletedTruthError("every truth page must be explicitly review_complete")
        rows = page.get("source_regions")
        if not isinstance(rows, list):
            raise Hz34CompletedTruthError("source_regions must be a list")
        disposition = page.get("page_disposition")
        if disposition != ("source_regions_recorded" if rows else "no_target_source_regions"):
            raise Hz34CompletedTruthError("page disposition does not match reviewed source regions")
        empty_pages += not rows
        page_rects: list[tuple[str, tuple[float, float, float, float]]] = []
        for expected_region, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise Hz34CompletedTruthError("source region must be an object")
            region_id = row.get("source_region_id")
            expected_id = f"p{expected_page:03d}-r{expected_region:03d}"
            if region_id != expected_id or not re.fullmatch(r"p\d{3}-r\d{3}", str(region_id)):
                raise Hz34CompletedTruthError("source region IDs must be deterministic and sequential")
            if region_id in ids:
                raise Hz34CompletedTruthError("source region IDs must be globally unique")
            ids.add(str(region_id))
            scope, boundary, confidence = row.get("scope_classification"), row.get("boundary_state"), row.get("reviewer_confidence")
            if scope not in SOURCE_SCOPES:
                raise Hz34CompletedTruthError("invalid source scope classification")
            if boundary not in BOUNDARY_STATES:
                raise Hz34CompletedTruthError("invalid boundary state")
            if confidence not in CONFIDENCES:
                raise Hz34CompletedTruthError("invalid reviewer confidence")
            for optional in ("observed_label", "reviewer_note"):
                value = row.get(optional)
                if value is not None and not isinstance(value, str):
                    raise Hz34CompletedTruthError(f"{optional} must be string or null")
            rect = _rect(row, expected_width, expected_height)
            for other_id, other_rect in page_rects:
                if _positive_overlap(rect, other_rect):
                    raise Hz34CompletedTruthError(f"source truth rectangles overlap: {region_id} and {other_id}")
            page_rects.append((str(region_id), rect))
            scope_counts[str(scope)] += 1
            boundary_counts[str(boundary)] += 1
            total += 1
    if total <= 0:
        raise Hz34CompletedTruthError("completed source truth contains zero source regions")
    return {
        "page_count": EXPECTED_PAGES,
        "source_region_count": total,
        "in_scope_region_count": scope_counts["in_scope"],
        "excluded_non_target_region_count": scope_counts["excluded_non_target"],
        "partial_single_card_count": boundary_counts["partial_single_card"],
        "empty_reviewed_page_count": empty_pages,
    }


def validate_truth_file(truth_path: Path, review_pack_zip: Path) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    dimensions = validate_review_pack_zip(review_pack_zip)
    payload, raw = _json_bytes(truth_path)
    summary = validate_truth_payload(payload, dimensions)
    receipt = {
        "schema_version": 1,
        "strategy": RECEIPT_STRATEGY,
        "campaign_key": CAMPAIGN,
        "completed_source_truth_sha256": sha256_bytes(raw),
        "review_pack_artifact_id": REVIEW_PACK_ARTIFACT_ID,
        "review_pack_workflow_run_id": REVIEW_PACK_RUN_ID,
        "review_pack_artifact": REVIEW_PACK_ARTIFACT,
        "review_pack_artifact_digest": REVIEW_PACK_ARTIFACT_DIGEST,
        "review_pack_manifest_sha256": REVIEW_PACK_MANIFEST_SHA256,
        "blank_source_truth_ledger_sha256": BLANK_LEDGER_SHA256,
        "artifact_source_receipt_sha256": ARTIFACT_SOURCE_RECEIPT_SHA256,
        "source_sha256": SOURCE_SHA256,
        "source_pdf_sha256": PDF_SHA256,
        "freeze_manifest_sha256": FREEZE_MANIFEST_SHA256,
        **summary,
        "frozen_predictions_opened": False,
        "candidate_provenance_opened": False,
        "adjudication_started": False,
        "review_only": True,
        "promotion_ready": False,
    }
    return payload, receipt, raw


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate independently completed Netto hz34 source-card truth before candidate exposure.")
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--review-pack-zip", type=Path, required=True)
    parser.add_argument("--write-receipt", type=Path)
    args = parser.parse_args()
    _, receipt, _ = validate_truth_file(args.truth, args.review_pack_zip)
    encoded = receipt_bytes(receipt)
    if args.write_receipt:
        if args.write_receipt.exists() or args.write_receipt.is_symlink():
            raise Hz34CompletedTruthError("receipt output must be create-only")
        args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.write_receipt.write_bytes(encoded)
    print(json.dumps({**receipt, "receipt_sha256": sha256_bytes(encoded)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
