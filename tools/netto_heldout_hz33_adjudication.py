#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_heldout_completed_source_truth import (  # noqa: E402
    EXPECTED_COMPLETED_SHA256,
    validate_file as validate_completed_truth_file,
)
from netto_heldout_ownership_protocol import (  # noqa: E402
    ACCEPTANCE,
    file_sha256,
    validate_freeze_manifest,
    validate_freeze_receipt,
)

STRATEGY = "netto_hz33_heldout_ownership_adjudication_v1"
COORDINATE_SPACE = "unrotated_page_points"
TRUTH_CLASSES = {"single_source", "mixed_source", "excluded_control"}
EVIDENCE_GAP_CLASSES = {"unmatched_review_required", "scope_overlap_review_required"}
ALLOWED_ROUTES = {
    "single_center_group",
    "multiple_center_groups_review_required",
    "excluded_control",
}


class HeldoutAdjudicationError(ValueError):
    pass


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutAdjudicationError(f"{label} must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutAdjudicationError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise HeldoutAdjudicationError(f"{label} must contain an object")
    return payload


def _positive_overlap(a: list[float], b: list[float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _rect(value: Any, *, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise HeldoutAdjudicationError(f"{label} must contain four coordinates")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise HeldoutAdjudicationError(f"{label} contains non-finite coordinates")
    if result[2] <= result[0] or result[3] <= result[1]:
        raise HeldoutAdjudicationError(f"{label} must have positive area")
    return result


def _prediction_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if {"page_number", "cell_id", "rect_points", "geometry_group_route"} <= set(value):
                records.append(dict(value))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if not records:
        raise HeldoutAdjudicationError("frozen predictions contain no adjudicable cell records")
    seen: set[str] = set()
    for row in records:
        cell_id = str(row.get("cell_id") or "")
        if not cell_id or cell_id in seen:
            raise HeldoutAdjudicationError("prediction cell IDs must be non-empty and unique")
        seen.add(cell_id)
        route = row.get("geometry_group_route")
        if route not in ALLOWED_ROUTES:
            raise HeldoutAdjudicationError(f"unexpected frozen geometry route for {cell_id}: {route}")
        page = row.get("page_number")
        if not isinstance(page, int) or not (1 <= page <= 77):
            raise HeldoutAdjudicationError(f"invalid prediction page for {cell_id}")
        _rect(row.get("rect_points"), label=f"prediction rectangle {cell_id}")
    return records


def _collect_group_ids(row: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                name = str(key).lower()
                if name.endswith("_group_id") or name in {"group_id", "center_group_id"}:
                    if isinstance(child, (str, int)) and str(child):
                        values.add(str(child))
                elif name.endswith("_group_ids") and isinstance(child, list):
                    for item in child:
                        if isinstance(item, (str, int)) and str(item):
                            values.add(str(item))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(row)
    return sorted(values)


def _truth_pages(payload: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != 77:
        raise HeldoutAdjudicationError("completed truth page count mismatch")
    result: dict[int, dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, Mapping):
            raise HeldoutAdjudicationError("completed truth page row must be an object")
        number = page.get("page_number")
        if not isinstance(number, int) or number in result:
            raise HeldoutAdjudicationError("completed truth page identity mismatch")
        result[number] = dict(page)
    return result


def _coordinate_spaces(payload: Any) -> set[str]:
    values: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if "coordinate_space" in value:
                values.add(str(value["coordinate_space"]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return values


def adjudicate(
    *,
    completed_truth_path: Path,
    predictions_path: Path,
    freeze_manifest_path: Path,
    freeze_receipt_path: Path,
) -> dict[str, Any]:
    truth_receipt, truth_plain = validate_completed_truth_file(completed_truth_path)
    if hashlib.sha256(truth_plain).hexdigest() != EXPECTED_COMPLETED_SHA256:
        raise HeldoutAdjudicationError("completed truth SHA mismatch after validation")
    truth = json.loads(truth_plain.decode("utf-8"))

    freeze_manifest = validate_freeze_manifest(_load_json(freeze_manifest_path, "freeze manifest"))
    freeze_receipt = _load_json(freeze_receipt_path, "freeze receipt")
    validate_freeze_receipt(freeze_manifest, freeze_receipt)

    predictions_sha = file_sha256(predictions_path, "frozen predictions")
    if predictions_sha != freeze_manifest["predictions_sha256"]:
        raise HeldoutAdjudicationError("frozen predictions SHA does not match freeze manifest")
    if predictions_sha != freeze_receipt["predictions_sha256"]:
        raise HeldoutAdjudicationError("frozen predictions SHA does not match freeze receipt")
    if truth.get("campaign_key") != freeze_manifest["campaign_key"]:
        raise HeldoutAdjudicationError("truth/freeze campaign mismatch")
    if truth.get("source_sha256") != freeze_manifest["source_sha256"]:
        raise HeldoutAdjudicationError("truth/freeze source identity mismatch")
    if truth.get("freeze_manifest_sha256") != freeze_receipt["freeze_manifest_sha256"]:
        raise HeldoutAdjudicationError("truth/freeze logical identity mismatch")
    if freeze_receipt.get("truth_available_at_freeze") is not False:
        raise HeldoutAdjudicationError("freeze receipt indicates truth leakage")

    predictions = _load_json(predictions_path, "frozen predictions")
    spaces = _coordinate_spaces(predictions)
    if spaces and spaces != {COORDINATE_SPACE}:
        raise HeldoutAdjudicationError(f"prediction coordinate-space mismatch: {sorted(spaces)}")
    records = _prediction_records(predictions)
    truth_pages = _truth_pages(truth)

    rows: list[dict[str, Any]] = []
    group_to_cells: dict[tuple[int, str], set[str]] = defaultdict(set)
    for prediction in records:
        cell_id = str(prediction["cell_id"])
        page_number = int(prediction["page_number"])
        prediction_rect = _rect(prediction["rect_points"], label=f"prediction rectangle {cell_id}")
        page = truth_pages[page_number]
        width = float(page["page_width_points"])
        height = float(page["page_height_points"])
        if prediction_rect[0] < 0 or prediction_rect[1] < 0 or prediction_rect[2] > width or prediction_rect[3] > height:
            raise HeldoutAdjudicationError(f"prediction rectangle is outside source page: {cell_id}")

        in_scope: list[str] = []
        excluded: list[str] = []
        for source in page["source_regions"]:
            source_rect = _rect(source["rect_points"], label=f"source rectangle {source['source_region_id']}")
            if not _positive_overlap(prediction_rect, source_rect):
                continue
            if source["source_scope"] == "in_scope":
                in_scope.append(source["source_region_id"])
            elif source["source_scope"] == "excluded_non_target":
                excluded.append(source["source_region_id"])
            else:
                raise HeldoutAdjudicationError("unexpected source-truth scope")

        if len(in_scope) == 1 and not excluded:
            truth_class = "single_source"
        elif len(in_scope) >= 2 and not excluded:
            truth_class = "mixed_source"
        elif not in_scope and excluded:
            truth_class = "excluded_control"
        elif not in_scope and not excluded:
            truth_class = "unmatched_review_required"
        else:
            truth_class = "scope_overlap_review_required"

        group_ids = _collect_group_ids(prediction)
        for group_id in group_ids:
            group_to_cells[(page_number, group_id)].add(cell_id)
        rows.append(
            {
                "cell_id": cell_id,
                "page_number": page_number,
                "rect_points": prediction_rect,
                "geometry_group_route": prediction["geometry_group_route"],
                "truth_class": truth_class,
                "in_scope_truth_ids": sorted(in_scope),
                "excluded_truth_ids": sorted(excluded),
                "group_ids": group_ids,
            }
        )

    truth_counts = Counter(row["truth_class"] for row in rows)
    route_counts = Counter(row["geometry_group_route"] for row in rows)
    reviewed = [row for row in rows if row["truth_class"] in TRUTH_CLASSES]
    auto_single = [row for row in rows if row["geometry_group_route"] == "single_center_group"]
    auto_single_tp = sum(row["truth_class"] == "single_source" for row in auto_single)
    auto_single_fp = len(auto_single) - auto_single_tp
    auto_precision = auto_single_tp / len(auto_single) if auto_single else 0.0
    mixed_auto_single = sum(
        row["truth_class"] == "mixed_source" and row["geometry_group_route"] == "single_center_group"
        for row in rows
    )
    excluded_auto = sum(
        row["truth_class"] == "excluded_control" and row["geometry_group_route"] == "single_center_group"
        for row in rows
    )
    reuse = [
        {"page_number": page, "group_id": group_id, "cell_ids": sorted(cell_ids)}
        for (page, group_id), cell_ids in sorted(group_to_cells.items())
        if len(cell_ids) > 1
    ]

    metrics = {
        "prediction_records": len(rows),
        "route_counts": dict(sorted(route_counts.items())),
        "truth_counts": dict(sorted(truth_counts.items())),
        "reviewed_cells": len(reviewed),
        "single_source_cells": truth_counts["single_source"],
        "mixed_source_cells": truth_counts["mixed_source"],
        "excluded_control_cells": truth_counts["excluded_control"],
        "unmatched_review_required": truth_counts["unmatched_review_required"],
        "scope_overlap_review_required": truth_counts["scope_overlap_review_required"],
        "auto_single_count": len(auto_single),
        "auto_single_true_positive": auto_single_tp,
        "auto_single_false_positive": auto_single_fp,
        "auto_single_precision": round(auto_precision, 12),
        "mixed_source_auto_single": mixed_auto_single,
        "excluded_control_auto_eligible": excluded_auto,
        "cross_cell_group_reuse": len(reuse),
    }
    checks = {
        "minimum_reviewed_cells": metrics["reviewed_cells"] >= ACCEPTANCE["minimum_reviewed_cells"],
        "minimum_mixed_source_cells": metrics["mixed_source_cells"] >= ACCEPTANCE["minimum_mixed_source_cells"],
        "maximum_mixed_source_auto_single": metrics["mixed_source_auto_single"] <= ACCEPTANCE["maximum_mixed_source_auto_single"],
        "maximum_excluded_control_auto_eligible": metrics["excluded_control_auto_eligible"] <= ACCEPTANCE["maximum_excluded_control_auto_eligible"],
        "minimum_auto_single_precision": metrics["auto_single_precision"] >= ACCEPTANCE["minimum_auto_single_precision"],
        "maximum_cross_cell_group_reuse": metrics["cross_cell_group_reuse"] <= ACCEPTANCE["maximum_cross_cell_group_reuse"],
    }

    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "protocol": "netto-heldout-ownership-v1",
        "campaign_key": freeze_manifest["campaign_key"],
        "source_sha256": freeze_manifest["source_sha256"],
        "freeze_manifest_sha256": freeze_receipt["freeze_manifest_sha256"],
        "predictions_sha256": predictions_sha,
        "completed_source_truth_sha256": EXPECTED_COMPLETED_SHA256,
        "truth_receipt": truth_receipt,
        "coordinate_space": COORDINATE_SPACE,
        "acceptance": dict(ACCEPTANCE),
        "metrics": metrics,
        "acceptance_checks": checks,
        "acceptance_pass": all(checks.values()),
        "cross_cell_group_reuse_rows": reuse,
        "rows": sorted(rows, key=lambda row: (row["page_number"], row["cell_id"])),
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "review_only": True,
        "promotion_ready": False,
    }


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate frozen hz33 ownership predictions against immutable source truth")
    parser.add_argument("--completed-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--freeze-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-acceptance", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise HeldoutAdjudicationError("adjudication output must be create-only")
    payload = adjudicate(
        completed_truth_path=args.completed_truth,
        predictions_path=args.predictions,
        freeze_manifest_path=args.freeze_manifest,
        freeze_receipt_path=args.freeze_receipt,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(payload))
    print(json.dumps({"acceptance_pass": payload["acceptance_pass"], **payload["metrics"]}, sort_keys=True))
    if args.require_acceptance and not payload["acceptance_pass"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
