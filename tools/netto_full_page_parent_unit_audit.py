#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from netto_heldout_completed_source_truth import (
    EXPECTED_LEDGER_SHA,
    validate_file as validate_truth_file,
)
from netto_heldout_prediction_group_adjudication import adjudicate_group

SCHEMA_VERSION = 1
STRATEGY = "netto_full_page_parent_unit_audit_v1"
CANDIDATE_STRATEGY = "existing_vector_container_v1"
CAMPAIGN = "hz33_hasb"
STORE = "5659"
SCOPE = "family_primary_netto"
VALID_FROM = "2026-08-10"
VALID_UNTIL = "2026-08-15"
SOURCE_SHA = "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb"
PDF_SHA = "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba"
SOURCE_EVIDENCE_SHA = "49e22d29b16eacf0d316f20105de2c25e3d9b3c2ae231d0bd24d0d18036f5fd4"
PREDICTIONS_SHA = "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94"
PARSER_IDENTITY = "netto-visual-geometry-shadow-v3-unrotated-page-space"
PAGE_COUNT = 77
RECT_MIN_WIDTH_FRACTION = 0.10
RECT_MIN_HEIGHT_FRACTION = 0.06
TARGET_PARENT_PRECISION = 0.98


class ParentUnitAuditError(ValueError):
    pass


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _load_json(path: Path, *, expected_sha: str, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ParentUnitAuditError(f"{label} must be a regular non-symlink file")
    if _sha_file(path) != expected_sha:
        raise ParentUnitAuditError(f"{label} SHA mismatch")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ParentUnitAuditError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ParentUnitAuditError(f"{label} must contain a JSON object")
    return payload


def _bbox(raw: Any, *, label: str) -> tuple[float, float, float, float]:
    if isinstance(raw, Mapping):
        values = [raw.get(key) for key in ("x0", "y0", "x1", "y1")]
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = list(raw)
    else:
        raise ParentUnitAuditError(f"invalid {label}")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise ParentUnitAuditError(f"non-numeric {label}")
    x0, y0, x1, y1 = (float(value) for value in values)
    if not all(math.isfinite(value) for value in (x0, y0, x1, y1)):
        raise ParentUnitAuditError(f"non-finite {label}")
    if not (x1 > x0 and y1 > y0):
        raise ParentUnitAuditError(f"empty {label}")
    return x0, y0, x1, y1


def _center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def _contains_point(
    box: tuple[float, float, float, float], point: tuple[float, float]
) -> bool:
    # Half-open right/bottom edges match the held-out truth adjudicator and
    # avoid tolerance fitting at shared source boundaries.
    return box[0] <= point[0] < box[2] and box[1] <= point[1] < box[3]


def _validate_common_contract(
    source: dict[str, Any], predictions: dict[str, Any]
) -> None:
    expected_source = {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "strategy": "netto_heldout_all_pages_source_evidence_v1",
        "store_external_id": STORE,
        "scope": SCOPE,
        "campaign_key": CAMPAIGN,
        "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
        "source_identity_sha256": SOURCE_SHA,
        "source_pdf_sha256": PDF_SHA,
        "prediction_parser_identity": PARSER_IDENTITY,
        "page_count": PAGE_COUNT,
        "capture_scope": "all_pdf_pages",
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
    }
    expected_predictions = {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "strategy": "netto_heldout_all_pages_predictions_v1",
        "store_external_id": STORE,
        "scope": SCOPE,
        "campaign_key": CAMPAIGN,
        "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
        "source_identity_sha256": SOURCE_SHA,
        "source_pdf_sha256": PDF_SHA,
        "prediction_parser_identity": PARSER_IDENTITY,
        "page_count": PAGE_COUNT,
        "capture_scope": "all_pdf_pages",
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
    }
    for key, expected in expected_source.items():
        if source.get(key) != expected:
            raise ParentUnitAuditError(f"source evidence contract mismatch: {key}")
    for key, expected in expected_predictions.items():
        if predictions.get(key) != expected:
            raise ParentUnitAuditError(f"prediction contract mismatch: {key}")
    if source.get("source_parser_identity") in (None, ""):
        raise ParentUnitAuditError("source parser identity is missing")

    source_pages = source.get("pages")
    prediction_pages = predictions.get("pages")
    if not isinstance(source_pages, list) or len(source_pages) != PAGE_COUNT:
        raise ParentUnitAuditError("source evidence page count mismatch")
    if not isinstance(prediction_pages, list) or len(prediction_pages) != PAGE_COUNT:
        raise ParentUnitAuditError("prediction page count mismatch")


def _deduplicated_parent_rectangles(
    page_number: int,
    layout: Mapping[str, Any],
) -> list[dict[str, Any]]:
    page = layout.get("page") or {}
    width = float(page.get("width_points") or 0.0)
    height = float(page.get("height_points") or 0.0)
    if width <= 0.0 or height <= 0.0:
        raise ParentUnitAuditError("source page dimensions are invalid")
    rows = ((layout.get("vectors") or {}).get("rectangles") or [])
    if not isinstance(rows, list):
        raise ParentUnitAuditError("source vector rectangles must be a list")

    by_geometry: dict[tuple[float, float, float, float], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ParentUnitAuditError("source vector rectangle must be an object")
        box = _bbox(raw, label="source vector rectangle")
        width_fraction = (box[2] - box[0]) / width
        height_fraction = (box[3] - box[1]) / height
        if (
            width_fraction < RECT_MIN_WIDTH_FRACTION
            or height_fraction < RECT_MIN_HEIGHT_FRACTION
        ):
            continue
        key = tuple(round(value, 3) for value in box)
        candidate = {
            "bbox": [round(value, 3) for value in box],
            "width_fraction": round(width_fraction, 6),
            "height_fraction": round(height_fraction, 6),
            "area_fraction": round(width_fraction * height_fraction, 6),
        }
        prior = by_geometry.get(key)
        if prior is None or (
            candidate["area_fraction"], candidate["bbox"]
        ) < (prior["area_fraction"], prior["bbox"]):
            by_geometry[key] = candidate

    ordered = sorted(
        by_geometry.values(),
        key=lambda row: (
            row["area_fraction"],
            row["bbox"][1],
            row["bbox"][0],
            row["bbox"][3],
            row["bbox"][2],
        ),
    )
    for index, row in enumerate(ordered, start=1):
        row["parent_unit_id"] = f"p{page_number:03d}-vr{index:03d}"
    return ordered


def _group_atom_centers(
    group: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    spans_raw = analysis.get("spans")
    anchors_raw = analysis.get("price_anchors")
    if not isinstance(spans_raw, list) or not isinstance(anchors_raw, list):
        raise ParentUnitAuditError("prediction analysis spans/anchors are missing")
    spans = {int(row["index"]): row for row in spans_raw}
    anchors = {str(row["anchor_id"]): row for row in anchors_raw}
    if len(spans) != len(spans_raw) or len(anchors) != len(anchors_raw):
        raise ParentUnitAuditError("duplicate prediction atom identity")

    atoms: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, key in (
        ("title_span", "title_span_indexes"),
        ("ambiguous_span", "ambiguous_span_indexes"),
    ):
        indexes = group.get(key) or []
        if not isinstance(indexes, list):
            raise ParentUnitAuditError(f"{key} must be a list")
        for raw_index in indexes:
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise ParentUnitAuditError("span index must be an integer")
            span = spans.get(raw_index)
            if span is None:
                raise ParentUnitAuditError(f"group references missing span {raw_index}")
            identity = ("span", str(raw_index))
            if identity in seen:
                continue
            seen.add(identity)
            box = _bbox(span.get("bbox"), label="prediction span bbox")
            atoms.append(
                {
                    "atom_id": f"span:{raw_index}",
                    "atom_kind": kind,
                    "center": [round(value, 6) for value in _center(box)],
                }
            )

    anchor_ids = group.get("anchor_ids") or []
    if not isinstance(anchor_ids, list):
        raise ParentUnitAuditError("anchor_ids must be a list")
    for raw_anchor_id in anchor_ids:
        anchor_id = str(raw_anchor_id)
        anchor = anchors.get(anchor_id)
        if anchor is None:
            raise ParentUnitAuditError(f"group references missing anchor {anchor_id}")
        identity = ("anchor", anchor_id)
        if identity in seen:
            continue
        seen.add(identity)
        box = _bbox(anchor.get("bbox"), label="prediction anchor bbox")
        atoms.append(
            {
                "atom_id": f"anchor:{anchor_id}",
                "atom_kind": "price_anchor",
                "center": [round(value, 6) for value in _center(box)],
            }
        )
    return atoms


def freeze_parent_candidates(
    source: dict[str, Any], predictions: dict[str, Any]
) -> dict[str, Any]:
    """Freeze source/prediction-derived parent candidates without truth input."""
    _validate_common_contract(source, predictions)
    source_pages = {int(row["page_number"]): row for row in source["pages"]}
    prediction_pages = {int(row["page_number"]): row for row in predictions["pages"]}
    if set(source_pages) != set(range(1, PAGE_COUNT + 1)):
        raise ParentUnitAuditError("source pages are not exact 1..77")
    if set(prediction_pages) != set(range(1, PAGE_COUNT + 1)):
        raise ParentUnitAuditError("prediction pages are not exact 1..77")

    pages: list[dict[str, Any]] = []
    group_count = 0
    for page_number in range(1, PAGE_COUNT + 1):
        source_page = source_pages[page_number]
        prediction_page = prediction_pages[page_number]
        layout = source_page.get("layout")
        analysis = prediction_page.get("analysis")
        if not isinstance(layout, Mapping) or not isinstance(analysis, Mapping):
            raise ParentUnitAuditError("source/prediction page payload missing")
        if analysis.get("parser_identity") != PARSER_IDENTITY:
            raise ParentUnitAuditError("prediction page parser identity mismatch")
        source_dims = layout.get("page") or {}
        prediction_dims = analysis.get("page") or {}
        for key in ("width_points", "height_points"):
            if abs(float(source_dims.get(key) or 0.0) - float(prediction_dims.get(key) or 0.0)) > 0.001:
                raise ParentUnitAuditError("source/prediction page dimensions mismatch")

        parents = _deduplicated_parent_rectangles(page_number, layout)
        parent_by_id = {row["parent_unit_id"]: row for row in parents}
        groups_raw = analysis.get("groups")
        if not isinstance(groups_raw, list):
            raise ParentUnitAuditError("prediction groups are missing")
        frozen_groups: list[dict[str, Any]] = []
        seen_group_ids: set[str] = set()
        for group in groups_raw:
            if not isinstance(group, Mapping):
                raise ParentUnitAuditError("prediction group must be an object")
            group_id = str(group.get("group_id") or "")
            if not group_id or group_id in seen_group_ids:
                raise ParentUnitAuditError("duplicate or missing prediction group id")
            seen_group_ids.add(group_id)
            atoms = _group_atom_centers(group, analysis)
            candidate_ids: list[str] = []
            if atoms:
                for parent in parents:
                    box = tuple(float(value) for value in parent["bbox"])
                    if all(
                        _contains_point(box, (float(atom["center"][0]), float(atom["center"][1])))
                        for atom in atoms
                    ):
                        candidate_ids.append(str(parent["parent_unit_id"]))
            primary = candidate_ids[0] if candidate_ids else None
            if primary is not None and primary not in parent_by_id:
                raise ParentUnitAuditError("primary parent is not a frozen parent unit")
            frozen_groups.append(
                {
                    "prediction_unit_id": f"p{page_number:03d}-{group_id}",
                    "group_id": group_id,
                    "atom_count": len(atoms),
                    "atoms": atoms,
                    "candidate_parent_unit_ids": candidate_ids,
                    "candidate_parent_count": len(candidate_ids),
                    "primary_parent_unit_id": primary,
                }
            )
            group_count += 1

        pages.append(
            {
                "page_number": page_number,
                "parent_units": parents,
                "groups": frozen_groups,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "candidate_strategy": CANDIDATE_STRATEGY,
        "campaign_key": CAMPAIGN,
        "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
        "store_external_id": STORE,
        "scope": SCOPE,
        "source_sha256": SOURCE_SHA,
        "source_pdf_sha256": PDF_SHA,
        "source_evidence_sha256": SOURCE_EVIDENCE_SHA,
        "predictions_sha256": PREDICTIONS_SHA,
        "prediction_parser_identity": PARSER_IDENTITY,
        "page_count": PAGE_COUNT,
        "prediction_group_count": group_count,
        "parent_rectangle_policy": {
            "source": "source_evidence.layout.vectors.rectangles",
            "minimum_width_fraction": RECT_MIN_WIDTH_FRACTION,
            "minimum_height_fraction": RECT_MIN_HEIGHT_FRACTION,
            "dedup_coordinate_decimals": 3,
            "group_atom_mapping": "all_owned_atom_centers_inside_parent_half_open",
            "primary_parent_tiebreak": "smallest_area_then_geometry_then_parent_id",
        },
        "truth_used_for_candidate_construction": False,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "automatic_candidate_decision_frozen": False,
        "pages": pages,
    }
    payload["candidate_freeze_sha256"] = _sha_payload(payload)
    return payload


def _evaluate_parent(
    group_rows: list[dict[str, Any]],
    group_truth: Mapping[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    source_regions: set[str] = set()
    outcomes: list[str] = []
    for group in group_rows:
        truth = group_truth[group["prediction_unit_id"]]
        outcome = str(truth["outcome"])
        outcomes.append(outcome)
        source_regions.update(str(value) for value in truth.get("in_scope_source_region_ids") or [])
    if outcomes and all(outcome == "single_source" for outcome in outcomes) and len(source_regions) == 1:
        return "safe_single_source", sorted(source_regions)
    if outcomes and all(outcome == "excluded_control" for outcome in outcomes):
        return "excluded_only", []
    if any(outcome.startswith("unresolved_") for outcome in outcomes):
        return "unresolved", sorted(source_regions)
    return "unsafe_cross_source", sorted(source_regions)


def evaluate_frozen_candidates(
    candidate: dict[str, Any],
    predictions: dict[str, Any],
    truth_payload: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate an already-frozen candidate against completed hz33 truth."""
    candidate_sha = candidate.get("candidate_freeze_sha256")
    clone = {key: value for key, value in candidate.items() if key != "candidate_freeze_sha256"}
    if candidate_sha != _sha_payload(clone):
        raise ParentUnitAuditError("candidate freeze SHA mismatch")
    if candidate.get("truth_used_for_candidate_construction") is not False:
        raise ParentUnitAuditError("candidate construction truth-isolation contract failed")

    prediction_pages = {int(row["page_number"]): row for row in predictions["pages"]}
    truth_pages = {int(row["page_number"]): row for row in truth_payload["pages"]}
    group_truth: dict[str, dict[str, Any]] = {}
    for page_number in range(1, PAGE_COUNT + 1):
        analysis = prediction_pages[page_number]["analysis"]
        spans = {int(row["index"]): row for row in analysis["spans"]}
        anchors = {str(row["anchor_id"]): row for row in analysis["price_anchors"]}
        source_regions = truth_pages[page_number]["source_regions"]
        for group in analysis["groups"]:
            row = adjudicate_group(
                page_number=page_number,
                group=group,
                spans=spans,
                anchors=anchors,
                source_regions=source_regions,
            )
            group_truth[row["prediction_unit_id"]] = row

    parent_rows: list[dict[str, Any]] = []
    zero_parent_groups = 0
    one_parent_groups = 0
    multi_parent_groups = 0
    assigned_groups = 0
    candidate_groups_by_page: dict[int, dict[str, dict[str, Any]]] = {}
    for page in candidate["pages"]:
        page_number = int(page["page_number"])
        candidate_groups_by_page[page_number] = {
            str(row["prediction_unit_id"]): row for row in page["groups"]
        }
        assigned: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for group in page["groups"]:
            count = int(group["candidate_parent_count"])
            if count == 0:
                zero_parent_groups += 1
            elif count == 1:
                one_parent_groups += 1
            else:
                multi_parent_groups += 1
            primary = group.get("primary_parent_unit_id")
            if primary is not None:
                assigned[str(primary)].append(group)
                assigned_groups += 1
        for parent in page["parent_units"]:
            parent_id = str(parent["parent_unit_id"])
            groups = assigned.get(parent_id, [])
            if not groups:
                continue
            classification, source_region_ids = _evaluate_parent(groups, group_truth)
            parent_rows.append(
                {
                    "page_number": page_number,
                    "parent_unit_id": parent_id,
                    "bbox": parent["bbox"],
                    "group_count": len(groups),
                    "prediction_unit_ids": sorted(
                        str(group["prediction_unit_id"]) for group in groups
                    ),
                    "truth_classification": classification,
                    "in_scope_source_region_ids": source_region_ids,
                }
            )

    counts = Counter(row["truth_classification"] for row in parent_rows)
    multi_rows = [row for row in parent_rows if int(row["group_count"]) >= 2]
    multi_counts = Counter(row["truth_classification"] for row in multi_rows)
    overall_precision = (
        counts["safe_single_source"] / len(parent_rows) if parent_rows else 0.0
    )
    multi_precision = (
        multi_counts["safe_single_source"] / len(multi_rows) if multi_rows else 0.0
    )
    suitable = (
        overall_precision >= TARGET_PARENT_PRECISION
        and multi_precision >= TARGET_PARENT_PRECISION
        and zero_parent_groups == 0
        and multi_parent_groups == 0
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "candidate_strategy": CANDIDATE_STRATEGY,
        "candidate_freeze_sha256": candidate_sha,
        "completed_source_truth_sha256": EXPECTED_LEDGER_SHA,
        "truth_loaded_only_after_candidate_freeze": True,
        "prediction_group_count": int(candidate["prediction_group_count"]),
        "assigned_group_count": assigned_groups,
        "zero_candidate_parent_group_count": zero_parent_groups,
        "exactly_one_candidate_parent_group_count": one_parent_groups,
        "multiple_candidate_parent_group_count": multi_parent_groups,
        "assigned_parent_count": len(parent_rows),
        "parent_truth_counts": dict(sorted(counts.items())),
        "safe_single_parent_precision": round(overall_precision, 6),
        "multi_group_parent_count": len(multi_rows),
        "multi_group_parent_truth_counts": dict(sorted(multi_counts.items())),
        "multi_group_safe_single_precision": round(multi_precision, 6),
        "target_parent_precision": TARGET_PARENT_PRECISION,
        "suitable_for_next_heldout_auto_single": suitable,
        "decision": "candidate_rejected" if not suitable else "candidate_requires_separate_freeze_gate",
        "automatic_candidate_decision_frozen": False,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "parents": parent_rows,
    }


def run_audit(
    source_evidence_path: Path,
    predictions_path: Path,
    truth_path: Path,
) -> dict[str, Any]:
    source = _load_json(
        source_evidence_path,
        expected_sha=SOURCE_EVIDENCE_SHA,
        label="frozen source evidence",
    )
    predictions = _load_json(
        predictions_path,
        expected_sha=PREDICTIONS_SHA,
        label="frozen predictions",
    )
    candidate = freeze_parent_candidates(source, predictions)
    truth, truth_receipt = validate_truth_file(truth_path)
    if truth_receipt.get("completed_source_truth_sha256") != EXPECTED_LEDGER_SHA:
        raise ParentUnitAuditError("completed source truth identity mismatch")
    evaluation = evaluate_frozen_candidates(candidate, predictions, truth)
    return {
        "schema_version": SCHEMA_VERSION,
        "strategy": STRATEGY,
        "candidate_freeze": candidate,
        "evaluation": evaluation,
    }


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit full-page source-derived parent-unit candidates on exposed hz33 evidence."
    )
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ParentUnitAuditError("audit output must be create-only")
    payload = run_audit(args.source_evidence, args.predictions, args.truth)
    encoded = _json_bytes(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    evaluation = payload["evaluation"]
    print(
        json.dumps(
            {
                "audit_sha256": hashlib.sha256(encoded).hexdigest(),
                "candidate_freeze_sha256": payload["candidate_freeze"]["candidate_freeze_sha256"],
                "assigned_group_count": evaluation["assigned_group_count"],
                "assigned_parent_count": evaluation["assigned_parent_count"],
                "safe_single_parent_precision": evaluation["safe_single_parent_precision"],
                "multi_group_safe_single_precision": evaluation["multi_group_safe_single_precision"],
                "suitable_for_next_heldout_auto_single": evaluation["suitable_for_next_heldout_auto_single"],
                "decision": evaluation["decision"],
                "promotion_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
