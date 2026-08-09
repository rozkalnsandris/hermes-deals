#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_heldout_completed_source_truth import (  # noqa: E402
    EXPECTED_LEDGER_SHA,
    validate_file as validate_truth_file,
)
from netto_heldout_ownership_protocol import ACCEPTANCE, PROTOCOL_NAME  # noqa: E402

STRATEGY = "netto_heldout_prediction_group_adjudication_v1"
EXPECTED_PREDICTIONS_SHA = "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94"
EXPECTED_CAMPAIGN = "hz33_hasb"
EXPECTED_STORE = "5659"
EXPECTED_SCOPE = "family_primary_netto"
EXPECTED_VALID_FROM = "2026-08-10"
EXPECTED_VALID_UNTIL = "2026-08-15"
EXPECTED_SOURCE_SHA = "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb"
EXPECTED_PDF_SHA = "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba"
EXPECTED_PARSER = "netto-visual-geometry-shadow-v3-unrotated-page-space"
EXPECTED_PAGES = 77
EXPECTED_ACCEPTANCE = {
    "minimum_reviewed_cells": 50,
    "minimum_mixed_source_cells": 5,
    "maximum_mixed_source_auto_single": 0,
    "maximum_excluded_control_auto_eligible": 0,
    "minimum_auto_single_precision": 0.98,
    "maximum_cross_cell_group_reuse": 0,
}

OUTCOME_CLASSES = {"single_source", "mixed_source", "excluded_control"}


class HeldoutAdjudicationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutAdjudicationError(f"input must be a regular non-symlink file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutAdjudicationError(f"invalid JSON input: {path}") from exc
    if not isinstance(payload, dict):
        raise HeldoutAdjudicationError("JSON input must contain an object")
    return payload


def _bbox(raw: Any) -> tuple[float, float, float, float]:
    if isinstance(raw, Mapping):
        values = [raw.get(key) for key in ("x0", "y0", "x1", "y1")]
    elif isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = list(raw)
    else:
        raise HeldoutAdjudicationError("atom bbox must contain x0/y0/x1/y1")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        raise HeldoutAdjudicationError("atom bbox must be numeric")
    result = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in result):
        raise HeldoutAdjudicationError("atom bbox must be finite")
    if not (result[0] < result[2] and result[1] < result[3]):
        raise HeldoutAdjudicationError("atom bbox must have positive area")
    return result


def _region_for_center(
    bbox: tuple[float, float, float, float],
    source_regions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    cx = (bbox[0] + bbox[2]) / 2.0
    cy = (bbox[1] + bbox[3]) / 2.0
    hits: list[dict[str, Any]] = []
    for region in source_regions:
        rect = region["rect_points"]
        x0, y0, x1, y1 = (float(value) for value in rect)
        # Half-open right/bottom edges make touching frozen source rectangles
        # deterministic without inventing an overlap tolerance.
        if x0 <= cx < x1 and y0 <= cy < y1:
            hits.append(region)
    if len(hits) > 1:
        raise HeldoutAdjudicationError("one evidence atom maps to overlapping source truth regions")
    return hits[0] if hits else None


def _group_atoms(
    group: Mapping[str, Any],
    spans: Mapping[int, Mapping[str, Any]],
    anchors: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind, indexes in (
        ("title_span", group.get("title_span_indexes") or []),
        ("ambiguous_span", group.get("ambiguous_span_indexes") or []),
    ):
        if not isinstance(indexes, list):
            raise HeldoutAdjudicationError(f"{kind} indexes must be a list")
        for raw_index in indexes:
            if isinstance(raw_index, bool) or not isinstance(raw_index, int):
                raise HeldoutAdjudicationError("span index must be an integer")
            span = spans.get(raw_index)
            if span is None:
                raise HeldoutAdjudicationError(f"group references missing span {raw_index}")
            identity = ("span", str(raw_index))
            if identity in seen:
                continue
            seen.add(identity)
            atoms.append({"kind": kind, "id": f"span:{raw_index}", "bbox": _bbox(span.get("bbox"))})

    anchor_ids = group.get("anchor_ids") or []
    if not isinstance(anchor_ids, list):
        raise HeldoutAdjudicationError("anchor_ids must be a list")
    for raw_anchor_id in anchor_ids:
        anchor_id = str(raw_anchor_id)
        anchor = anchors.get(anchor_id)
        if anchor is None:
            raise HeldoutAdjudicationError(f"group references missing price anchor {anchor_id}")
        identity = ("anchor", anchor_id)
        if identity in seen:
            continue
        seen.add(identity)
        atoms.append({"kind": "price_anchor", "id": f"anchor:{anchor_id}", "bbox": _bbox(anchor.get("bbox"))})
    return atoms


def adjudicate_group(
    *,
    page_number: int,
    group: Mapping[str, Any],
    spans: Mapping[int, Mapping[str, Any]],
    anchors: Mapping[str, Mapping[str, Any]],
    source_regions: list[dict[str, Any]],
) -> dict[str, Any]:
    atoms = _group_atoms(group, spans, anchors)
    in_scope: set[str] = set()
    excluded: set[str] = set()
    unmatched: list[str] = []
    atom_rows: list[dict[str, Any]] = []

    for atom in atoms:
        region = _region_for_center(atom["bbox"], source_regions)
        if region is None:
            unmatched.append(atom["id"])
            region_id = None
            scope = None
        else:
            region_id = str(region["source_region_id"])
            scope = str(region["scope_classification"])
            if scope == "in_scope":
                in_scope.add(region_id)
            elif scope == "excluded_non_target":
                excluded.add(region_id)
            else:
                raise HeldoutAdjudicationError("unexpected source truth scope")
        atom_rows.append(
            {
                "atom_id": atom["id"],
                "kind": atom["kind"],
                "source_region_id": region_id,
                "source_scope": scope,
            }
        )

    if len(in_scope) >= 2:
        outcome = "mixed_source"
    elif len(in_scope) == 1 and not excluded and not unmatched:
        outcome = "single_source"
    elif not in_scope and excluded and not unmatched:
        outcome = "excluded_control"
    elif not atoms:
        outcome = "unresolved_no_atoms"
    elif len(in_scope) == 1 and excluded:
        outcome = "unresolved_cross_scope"
    elif unmatched:
        outcome = "unresolved_unmapped_atoms"
    else:
        outcome = "unresolved_other"

    group_id = str(group.get("group_id") or "")
    if not re.fullmatch(r"g\d{3}", group_id):
        raise HeldoutAdjudicationError("group_id must match gNNN")
    route = group.get("route")
    production_eligible = group.get("production_eligible")
    if not isinstance(route, str) or not isinstance(production_eligible, bool):
        raise HeldoutAdjudicationError("frozen group route/production_eligible is invalid")

    return {
        "prediction_unit_id": f"p{page_number:03d}-{group_id}",
        "page_number": page_number,
        "group_id": group_id,
        "outcome": outcome,
        "in_scope_source_region_ids": sorted(in_scope),
        "excluded_source_region_ids": sorted(excluded),
        "unmatched_atom_ids": unmatched,
        "atom_count": len(atoms),
        "atoms": atom_rows,
        "frozen_route": route,
        "frozen_production_eligible": production_eligible,
    }


def _validate_predictions(predictions: dict[str, Any], path: Path) -> None:
    if _sha256(path) != EXPECTED_PREDICTIONS_SHA:
        raise HeldoutAdjudicationError("frozen predictions SHA mismatch")
    expected = {
        "schema_version": 1,
        "protocol": PROTOCOL_NAME,
        "strategy": "netto_heldout_all_pages_predictions_v1",
        "store_external_id": EXPECTED_STORE,
        "scope": EXPECTED_SCOPE,
        "campaign_key": EXPECTED_CAMPAIGN,
        "campaign_window": {"start": EXPECTED_VALID_FROM, "end": EXPECTED_VALID_UNTIL},
        "source_identity_sha256": EXPECTED_SOURCE_SHA,
        "source_pdf_sha256": EXPECTED_PDF_SHA,
        "prediction_parser_identity": EXPECTED_PARSER,
        "page_count": EXPECTED_PAGES,
        "capture_scope": "all_pdf_pages",
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
    }
    for key, value in expected.items():
        if predictions.get(key) != value:
            raise HeldoutAdjudicationError(f"frozen prediction contract mismatch: {key}")


def _metric(status: str, observed: Any, threshold: Any, reason: str | None = None) -> dict[str, Any]:
    row = {"status": status, "observed": observed, "threshold": threshold}
    if reason:
        row["reason"] = reason
    return row


def build_metrics(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    if ACCEPTANCE != EXPECTED_ACCEPTANCE:
        raise HeldoutAdjudicationError("predeclared held-out acceptance contract drift")
    counts = Counter(row["outcome"] for row in rows)
    resolved = sum(counts[name] for name in OUTCOME_CLASSES)
    automatic = [row for row in rows if row["frozen_production_eligible"] is True]
    mixed_auto = sum(row["outcome"] == "mixed_source" for row in automatic)
    excluded_auto = sum(row["outcome"] == "excluded_control" for row in automatic)
    auto_single_correct = sum(row["outcome"] == "single_source" for row in automatic)
    auto_precision = auto_single_correct / len(automatic) if automatic else None

    metrics = {
        "minimum_reviewed_cells": _metric(
            "PASS" if resolved >= ACCEPTANCE["minimum_reviewed_cells"] else "FAIL",
            resolved,
            ACCEPTANCE["minimum_reviewed_cells"],
            "Legacy protocol term 'cells' is reported using resolved frozen prediction groups because the all-page capture contains groups, not parent-cell objects.",
        ),
        "minimum_mixed_source_cells": _metric(
            "PASS" if counts["mixed_source"] >= ACCEPTANCE["minimum_mixed_source_cells"] else "FAIL",
            counts["mixed_source"],
            ACCEPTANCE["minimum_mixed_source_cells"],
            "Legacy protocol term 'cells' is reported using frozen prediction groups.",
        ),
        "maximum_mixed_source_auto_single": _metric(
            "PASS" if mixed_auto <= ACCEPTANCE["maximum_mixed_source_auto_single"] else "FAIL",
            mixed_auto,
            ACCEPTANCE["maximum_mixed_source_auto_single"],
            "Literal frozen production_eligible=true is the only automatic-eligibility signal used.",
        ),
        "maximum_excluded_control_auto_eligible": _metric(
            "PASS" if excluded_auto <= ACCEPTANCE["maximum_excluded_control_auto_eligible"] else "FAIL",
            excluded_auto,
            ACCEPTANCE["maximum_excluded_control_auto_eligible"],
            "Literal frozen production_eligible=true is the only automatic-eligibility signal used.",
        ),
        "minimum_auto_single_precision": (
            _metric(
                "PASS" if auto_precision >= ACCEPTANCE["minimum_auto_single_precision"] else "FAIL",
                auto_precision,
                ACCEPTANCE["minimum_auto_single_precision"],
            )
            if auto_precision is not None
            else _metric(
                "NOT_EVALUABLE",
                None,
                ACCEPTANCE["minimum_auto_single_precision"],
                "The frozen held-out predictions contain zero production_eligible groups; post-truth auto-single inference is prohibited.",
            )
        ),
        "maximum_cross_cell_group_reuse": _metric(
            "NOT_EVALUABLE",
            None,
            ACCEPTANCE["maximum_cross_cell_group_reuse"],
            "The frozen all-page prediction schema has no parent-cell assignment/provenance from which cross-cell group reuse can be measured.",
        ),
    }
    promotion_ready = all(row["status"] == "PASS" for row in metrics.values())
    return metrics, promotion_ready


def adjudicate(predictions_path: Path, truth_path: Path) -> dict[str, Any]:
    truth, truth_receipt = validate_truth_file(truth_path)
    if truth_receipt["completed_source_truth_sha256"] != EXPECTED_LEDGER_SHA:
        raise HeldoutAdjudicationError("completed truth identity mismatch")
    predictions = _load_json(predictions_path)
    _validate_predictions(predictions, predictions_path)

    truth_pages = {int(page["page_number"]): page for page in truth["pages"]}
    prediction_pages = predictions.get("pages")
    if not isinstance(prediction_pages, list) or len(prediction_pages) != EXPECTED_PAGES:
        raise HeldoutAdjudicationError("frozen predictions must contain 77 pages")

    rows: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    for expected_page_number, page_row in enumerate(prediction_pages, start=1):
        if not isinstance(page_row, dict) or page_row.get("page_number") != expected_page_number:
            raise HeldoutAdjudicationError("prediction pages must be sequential 1..77")
        analysis = page_row.get("analysis")
        if not isinstance(analysis, dict) or analysis.get("parser_identity") != EXPECTED_PARSER:
            raise HeldoutAdjudicationError("page parser identity mismatch")
        analysis_page = analysis.get("page")
        truth_page = truth_pages.get(expected_page_number)
        if not isinstance(analysis_page, dict) or truth_page is None:
            raise HeldoutAdjudicationError("prediction/truth page metadata missing")
        for dimension, truth_key in (("width_points", "page_width_points"), ("height_points", "page_height_points")):
            if abs(float(analysis_page.get(dimension)) - float(truth_page[truth_key])) > 0.001:
                raise HeldoutAdjudicationError("prediction/truth page dimensions mismatch")

        spans_raw = analysis.get("spans")
        anchors_raw = analysis.get("price_anchors")
        groups = analysis.get("groups")
        if not isinstance(spans_raw, list) or not isinstance(anchors_raw, list) or not isinstance(groups, list):
            raise HeldoutAdjudicationError("prediction page arrays are invalid")
        spans = {int(span["index"]): span for span in spans_raw}
        if len(spans) != len(spans_raw):
            raise HeldoutAdjudicationError("duplicate prediction span index")
        anchors = {str(anchor["anchor_id"]): anchor for anchor in anchors_raw}
        if len(anchors) != len(anchors_raw):
            raise HeldoutAdjudicationError("duplicate prediction anchor id")

        for group in groups:
            if not isinstance(group, dict):
                raise HeldoutAdjudicationError("prediction group must be an object")
            row = adjudicate_group(
                page_number=expected_page_number,
                group=group,
                spans=spans,
                anchors=anchors,
                source_regions=truth_page["source_regions"],
            )
            if row["prediction_unit_id"] in seen_units:
                raise HeldoutAdjudicationError("duplicate prediction unit id")
            seen_units.add(row["prediction_unit_id"])
            rows.append(row)

    counts = Counter(row["outcome"] for row in rows)
    route_counts = Counter(
        f"{row['frozen_route']}|production_eligible={str(row['frozen_production_eligible']).lower()}"
        for row in rows
    )
    metrics, promotion_ready = build_metrics(rows)
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "protocol": PROTOCOL_NAME,
        "campaign_key": EXPECTED_CAMPAIGN,
        "campaign_window": {"start": EXPECTED_VALID_FROM, "end": EXPECTED_VALID_UNTIL},
        "store_external_id": EXPECTED_STORE,
        "scope": EXPECTED_SCOPE,
        "source_sha256": EXPECTED_SOURCE_SHA,
        "source_pdf_sha256": EXPECTED_PDF_SHA,
        "prediction_parser_identity": EXPECTED_PARSER,
        "predictions_sha256": EXPECTED_PREDICTIONS_SHA,
        "completed_source_truth_sha256": EXPECTED_LEDGER_SHA,
        "mapping_strategy": "frozen_group_owned_atom_center_to_independent_source_region_v1",
        "coordinate_space": "unrotated_page_points",
        "prediction_unit": "frozen_geometry_group",
        "protocol_legacy_unit_term": "cell",
        "page_count": EXPECTED_PAGES,
        "prediction_group_count": len(rows),
        "resolved_prediction_group_count": sum(counts[name] for name in OUTCOME_CLASSES),
        "outcome_counts": dict(sorted(counts.items())),
        "frozen_route_counts": dict(sorted(route_counts.items())),
        "acceptance": dict(ACCEPTANCE),
        "metrics": metrics,
        "required_metric_not_evaluable_count": sum(
            row["status"] == "NOT_EVALUABLE" for row in metrics.values()
        ),
        "acceptance_all_pass": promotion_ready,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "rows": rows,
    }


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Adjudicate the frozen hz33 geometry groups against completed independent source truth.")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise HeldoutAdjudicationError("adjudication output must be create-only")
    payload = adjudicate(args.predictions, args.truth)
    encoded = _json_bytes(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    summary = {
        "adjudication_sha256": hashlib.sha256(encoded).hexdigest(),
        "prediction_group_count": payload["prediction_group_count"],
        "resolved_prediction_group_count": payload["resolved_prediction_group_count"],
        "outcome_counts": payload["outcome_counts"],
        "required_metric_not_evaluable_count": payload["required_metric_not_evaluable_count"],
        "acceptance_all_pass": payload["acceptance_all_pass"],
        "promotion_ready": payload["promotion_ready"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
