#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

EXPECTED_TRUTH_SHA256 = "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6"
EXPECTED_TRUTH_GZIP_SHA256 = "06ccb28e632d8eb6604741b58083a4dd8b45e0c24f8b945b87cd46ff405fbfaf"
EXPECTED_ADJUDICATION_SHA256 = "1d1975c4845fe1bdbd2dd97670fac2df28cc68894003322485c10d53826a818f"
EXPECTED_PREDICTIONS_SHA256 = "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94"
EXPECTED_TRUTH_RECEIPT_STRATEGY = "netto_heldout_completed_source_truth_receipt_v1"
EXPECTED_ADJUDICATION_RECEIPT_STRATEGY = "netto_hz33_heldout_adjudication_evidence_receipt_v2"
EXPECTED_ADJUDICATION_STRATEGY = "netto_heldout_prediction_group_adjudication_v1"
REPORT_STRATEGY = "netto_hz33_heldout_disagreement_taxonomy_v2"
EXPECTED_ROWS = 612
EXPECTED_OUTCOMES = {
    "excluded_control": 82,
    "mixed_source": 90,
    "single_source": 391,
    "unresolved_cross_scope": 1,
    "unresolved_unmapped_atoms": 48,
}
PRIMARY_CLASSES = (
    "unsafe_auto_single",
    "conservative_review",
    "missed_excluded",
    "over_excluded",
    "mixed_held_review",
    "unmatched_evidence_gap",
    "scope_overlap_evidence_gap",
    "correct_auto_single",
    "correct_excluded_control",
)
UNSAFE_OR_GAP_CLASSES = {
    "unsafe_auto_single",
    "missed_excluded",
    "over_excluded",
    "unmatched_evidence_gap",
    "scope_overlap_evidence_gap",
}
ALLOWED_OUTCOMES = set(EXPECTED_OUTCOMES)
ALLOWED_ROUTES = {
    "review_required",
    "multiple_center_groups_review_required",
    "single_center_group",
    "excluded_control",
}


class Hz33TaxonomyError(ValueError):
    pass


def _json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise Hz33TaxonomyError(f"{label} must be a regular file")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Hz33TaxonomyError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise Hz33TaxonomyError(f"{label} must contain a JSON object")
    return payload, raw


def _validate_truth(truth_path: Path, truth_receipt_path: Path) -> None:
    receipt, _ = _json_object(truth_receipt_path, "completed source truth receipt")
    expected = {
        "strategy": EXPECTED_TRUTH_RECEIPT_STRATEGY,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "compressed_payload_sha256": EXPECTED_TRUTH_GZIP_SHA256,
        "page_count": 77,
        "source_region_count": 341,
        "in_scope_region_count": 309,
        "excluded_non_target_region_count": 32,
        "partial_single_card_count": 9,
        "frozen_predictions_opened": False,
        "adjudication_started": False,
        "review_only": True,
        "promotion_ready": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise Hz33TaxonomyError(f"completed source truth receipt mismatch: {key}")

    if truth_path.is_symlink() or not truth_path.is_file():
        raise Hz33TaxonomyError("completed source truth must be a regular file")
    try:
        compressed = base64.b64decode(truth_path.read_text(encoding="ascii").strip(), validate=True)
    except (OSError, UnicodeError, ValueError) as exc:
        raise Hz33TaxonomyError("completed source truth must be canonical base64") from exc
    if hashlib.sha256(compressed).hexdigest() != EXPECTED_TRUTH_GZIP_SHA256:
        raise Hz33TaxonomyError("completed source truth compressed SHA mismatch")
    try:
        raw = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise Hz33TaxonomyError("completed source truth gzip is invalid") from exc
    if hashlib.sha256(raw).hexdigest() != EXPECTED_TRUTH_SHA256:
        raise Hz33TaxonomyError("completed source truth SHA mismatch")


def _validate_adjudication(
    adjudication_path: Path,
    receipt_path: Path,
) -> tuple[dict[str, Any], str]:
    receipt, _ = _json_object(receipt_path, "held-out adjudication receipt")
    adjudication, raw = _json_object(adjudication_path, "held-out adjudication")
    adjudication_sha = hashlib.sha256(raw).hexdigest()

    receipt_expected = {
        "schema_version": 2,
        "strategy": EXPECTED_ADJUDICATION_RECEIPT_STRATEGY,
        "adjudication_json_sha256": EXPECTED_ADJUDICATION_SHA256,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "predictions_sha256": EXPECTED_PREDICTIONS_SHA256,
        "prediction_group_count": EXPECTED_ROWS,
        "resolved_prediction_group_count": 563,
        "outcome_counts": EXPECTED_OUTCOMES,
        "acceptance_all_pass": False,
        "required_metric_not_evaluable_count": 2,
        "recomputed_during_freeze": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "review_only": True,
        "promotion_ready": False,
    }
    for key, value in receipt_expected.items():
        if receipt.get(key) != value:
            raise Hz33TaxonomyError(f"held-out adjudication receipt mismatch: {key}")
    if adjudication_sha != EXPECTED_ADJUDICATION_SHA256:
        raise Hz33TaxonomyError("held-out adjudication SHA mismatch")
    if receipt.get("adjudication_json_sha256") != adjudication_sha:
        raise Hz33TaxonomyError("held-out adjudication SHA/receipt binding mismatch")

    adjudication_expected = {
        "schema_version": 1,
        "strategy": EXPECTED_ADJUDICATION_STRATEGY,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "predictions_sha256": EXPECTED_PREDICTIONS_SHA256,
        "prediction_group_count": EXPECTED_ROWS,
        "resolved_prediction_group_count": 563,
        "outcome_counts": EXPECTED_OUTCOMES,
        "acceptance_all_pass": False,
        "required_metric_not_evaluable_count": 2,
        "prediction_unit": "frozen_geometry_group",
        "prediction_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
    }
    for key, value in adjudication_expected.items():
        if adjudication.get(key) != value:
            raise Hz33TaxonomyError(f"held-out adjudication mismatch: {key}")

    metrics = adjudication.get("metrics")
    if not isinstance(metrics, Mapping):
        raise Hz33TaxonomyError("held-out adjudication metrics missing")
    reuse_metric = metrics.get("maximum_cross_cell_group_reuse")
    if not isinstance(reuse_metric, Mapping) or reuse_metric.get("status") != "NOT_EVALUABLE":
        raise Hz33TaxonomyError("cross-cell reuse metric must remain NOT_EVALUABLE")
    if reuse_metric.get("observed") is not None:
        raise Hz33TaxonomyError("cross-cell reuse metric must not invent an observation")

    rows = adjudication.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_ROWS:
        raise Hz33TaxonomyError("held-out adjudication row count mismatch")
    return adjudication, adjudication_sha


def primary_class(outcome: str, route: str, production_eligible: bool) -> str:
    if outcome == "unresolved_unmapped_atoms":
        return "unmatched_evidence_gap"
    if outcome == "unresolved_cross_scope":
        return "scope_overlap_evidence_gap"
    if production_eligible and outcome != "single_source":
        return "unsafe_auto_single"
    if outcome == "excluded_control" and route != "excluded_control":
        return "missed_excluded"
    if route == "excluded_control" and outcome in {"single_source", "mixed_source"}:
        return "over_excluded"
    if outcome == "single_source" and not production_eligible:
        return "conservative_review"
    if outcome == "mixed_source" and not production_eligible:
        return "mixed_held_review"
    if outcome == "single_source" and production_eligible:
        return "correct_auto_single"
    if outcome == "excluded_control" and route == "excluded_control":
        return "correct_excluded_control"
    raise Hz33TaxonomyError(f"unclassified outcome/route state: {outcome}/{route}/{production_eligible}")


def diagnose(
    truth_path: Path,
    truth_receipt_path: Path,
    adjudication_path: Path,
    adjudication_receipt_path: Path,
) -> dict[str, Any]:
    _validate_truth(truth_path, truth_receipt_path)
    adjudication, adjudication_sha = _validate_adjudication(adjudication_path, adjudication_receipt_path)

    primary_counts: Counter[str] = Counter({name: 0 for name in PRIMARY_CLASSES})
    route_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    page_primary: dict[int, Counter[str]] = defaultdict(Counter)
    page_routes: dict[int, Counter[str]] = defaultdict(Counter)
    diagnostic_rows: list[dict[str, Any]] = []
    stable_ids: set[str] = set()

    for row in adjudication["rows"]:
        if not isinstance(row, Mapping):
            raise Hz33TaxonomyError("adjudication row must be an object")
        row_id = str(row.get("prediction_unit_id") or "")
        if not re.fullmatch(r"p\d{3}-g\d{3}", row_id) or row_id in stable_ids:
            raise Hz33TaxonomyError("prediction_unit_id must be unique and deterministic")
        stable_ids.add(row_id)
        page = row.get("page_number")
        if not isinstance(page, int) or not 1 <= page <= 77 or not row_id.startswith(f"p{page:03d}-"):
            raise Hz33TaxonomyError(f"invalid page binding for {row_id}")
        group_id = str(row.get("group_id") or "")
        if not re.fullmatch(r"g\d{3}", group_id):
            raise Hz33TaxonomyError(f"invalid group id for {row_id}")
        outcome = str(row.get("outcome") or "")
        route = str(row.get("frozen_route") or "")
        production_eligible = row.get("frozen_production_eligible")
        if outcome not in ALLOWED_OUTCOMES:
            raise Hz33TaxonomyError(f"unexpected outcome for {row_id}: {outcome}")
        if route not in ALLOWED_ROUTES:
            raise Hz33TaxonomyError(f"unexpected frozen route for {row_id}: {route}")
        if not isinstance(production_eligible, bool):
            raise Hz33TaxonomyError(f"invalid frozen eligibility for {row_id}")

        primary = primary_class(outcome, route, production_eligible)
        primary_counts[primary] += 1
        route_counts[route] += 1
        outcome_counts[outcome] += 1
        page_primary[page][primary] += 1
        page_routes[page][route] += 1

        source_ids = sorted({
            str(value)
            for key in ("in_scope_source_region_ids", "excluded_source_region_ids")
            for value in row.get(key, [])
        })
        unmatched_ids = sorted(str(value) for value in row.get("unmatched_atom_ids", []))
        diagnostic_rows.append({
            "row_id": row_id,
            "page_number": page,
            "group_id": group_id,
            "frozen_route": route,
            "frozen_production_eligible": production_eligible,
            "heldout_outcome": outcome,
            "primary_diagnostic_class": primary,
            "unsafe_or_evidence_gap": primary in UNSAFE_OR_GAP_CLASSES,
            "source_region_ids": source_ids,
            "unmatched_atom_ids": unmatched_ids,
        })

    if outcome_counts != Counter(EXPECTED_OUTCOMES):
        raise Hz33TaxonomyError("row outcomes do not match frozen receipt counts")
    if sum(primary_counts.values()) != EXPECTED_ROWS:
        raise Hz33TaxonomyError("every frozen row must receive exactly one primary class")

    page_summaries: list[dict[str, Any]] = []
    for page in sorted(page_primary):
        counts = Counter({name: 0 for name in PRIMARY_CLASSES})
        counts.update(page_primary[page])
        page_summaries.append({
            "page_number": page,
            "row_count": sum(counts.values()),
            "primary_counts": dict(sorted(counts.items())),
            "route_counts": dict(sorted(page_routes[page].items())),
            "unsafe_or_evidence_gap": sum(counts[name] for name in UNSAFE_OR_GAP_CLASSES),
            "conservative_review": counts["conservative_review"],
            "mixed_held_review": counts["mixed_held_review"],
        })
    page_hotspots = sorted(
        page_summaries,
        key=lambda item: (
            -item["unsafe_or_evidence_gap"],
            -item["conservative_review"],
            -item["mixed_held_review"],
            item["page_number"],
        ),
    )

    expected_primary = {
        "unsafe_auto_single": 0,
        "conservative_review": 391,
        "missed_excluded": 82,
        "over_excluded": 0,
        "mixed_held_review": 90,
        "unmatched_evidence_gap": 48,
        "scope_overlap_evidence_gap": 1,
        "correct_auto_single": 0,
        "correct_excluded_control": 0,
    }
    if dict(primary_counts) != expected_primary:
        raise Hz33TaxonomyError("diagnostic counts drifted from frozen evidence")

    return {
        "schema_version": 2,
        "strategy": REPORT_STRATEGY,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "adjudication_sha256": adjudication_sha,
        "predictions_sha256": EXPECTED_PREDICTIONS_SHA256,
        "row_count": EXPECTED_ROWS,
        "primary_counts": expected_primary,
        "route_counts": dict(sorted(route_counts.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "unsafe_or_evidence_gap_count": sum(primary_counts[name] for name in UNSAFE_OR_GAP_CLASSES),
        "conservative_review_count": primary_counts["conservative_review"],
        "mixed_held_review_count": primary_counts["mixed_held_review"],
        "cross_cell_group_reuse": {
            "status": "NOT_EVALUABLE",
            "observed": None,
            "reason": adjudication["metrics"]["maximum_cross_cell_group_reuse"]["reason"],
        },
        "page_summaries": page_summaries,
        "page_hotspots": page_hotspots,
        "rows": sorted(diagnostic_rows, key=lambda item: (item["page_number"], item["row_id"])),
        "source_review_reopened": False,
        "threshold_tuning_performed": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "scheduler_changed": False,
        "review_only": True,
        "promotion_ready": False,
    }


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify frozen hz33 held-out ownership disagreements without tuning")
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--truth-receipt", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--adjudication-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise Hz33TaxonomyError("diagnostic report output must be create-only")
    report = diagnose(args.truth, args.truth_receipt, args.adjudication, args.adjudication_receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(report))
    print(json.dumps({
        "row_count": report["row_count"],
        "primary_counts": report["primary_counts"],
        "cross_cell_group_reuse_status": report["cross_cell_group_reuse"]["status"],
        "review_only": report["review_only"],
        "promotion_ready": report["promotion_ready"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
