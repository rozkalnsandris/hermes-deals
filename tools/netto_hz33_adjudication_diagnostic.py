#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

EXPECTED_TRUTH_SHA256 = "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6"
EXPECTED_CAPTURE_RUN_ID = 31324156565
EXPECTED_CAPTURE_ARTIFACT_ID = 9041052231
EXPECTED_CAPTURE_DIGEST = "cc289165aaac8796b33391917edb03df1085a841b82c0183caaf4498277f3cf6"
EXPECTED_ADJUDICATION_STRATEGY = "netto_hz33_heldout_ownership_adjudication_v1"
EXPECTED_RECEIPT_STRATEGY = "netto_hz33_heldout_adjudication_evidence_receipt_v1"
REPORT_STRATEGY = "netto_hz33_heldout_disagreement_taxonomy_v1"
ALLOWED_ROUTES = {
    "single_center_group",
    "multiple_center_groups_review_required",
    "excluded_control",
}
ALLOWED_TRUTH = {
    "single_source",
    "mixed_source",
    "excluded_control",
    "unmatched_review_required",
    "scope_overlap_review_required",
}
UNSAFE_PRIMARY = {
    "unsafe_auto_single",
    "missed_excluded",
    "over_excluded",
    "unmatched_evidence_gap",
    "scope_overlap_evidence_gap",
}


class Hz33DiagnosticError(ValueError):
    pass


def _load(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise Hz33DiagnosticError(f"{label} must be a regular file")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Hz33DiagnosticError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise Hz33DiagnosticError(f"{label} must contain an object")
    return payload, raw


def _primary_class(truth_class: str, route: str) -> str:
    if truth_class == "unmatched_review_required":
        return "unmatched_evidence_gap"
    if truth_class == "scope_overlap_review_required":
        return "scope_overlap_evidence_gap"
    if route == "single_center_group" and truth_class != "single_source":
        return "unsafe_auto_single"
    if truth_class == "excluded_control" and route != "excluded_control":
        return "missed_excluded"
    if route == "excluded_control" and truth_class in {"single_source", "mixed_source"}:
        return "over_excluded"
    if truth_class == "single_source" and route == "multiple_center_groups_review_required":
        return "conservative_review"
    if truth_class == "mixed_source" and route == "multiple_center_groups_review_required":
        return "mixed_held_review"
    if truth_class == "single_source" and route == "single_center_group":
        return "correct_auto_single"
    if truth_class == "excluded_control" and route == "excluded_control":
        return "correct_excluded_control"
    raise Hz33DiagnosticError(f"unclassified route/truth combination: {route} / {truth_class}")


def diagnose(adjudication_path: Path, receipt_path: Path) -> dict[str, Any]:
    adjudication, adjudication_raw = _load(adjudication_path, "adjudication")
    receipt, _ = _load(receipt_path, "adjudication receipt")

    adjudication_sha = hashlib.sha256(adjudication_raw).hexdigest()
    if receipt.get("strategy") != EXPECTED_RECEIPT_STRATEGY:
        raise Hz33DiagnosticError("receipt strategy mismatch")
    if receipt.get("adjudication_sha256") != adjudication_sha:
        raise Hz33DiagnosticError("adjudication SHA does not match receipt")
    if receipt.get("completed_source_truth_sha256") != EXPECTED_TRUTH_SHA256:
        raise Hz33DiagnosticError("completed truth SHA mismatch")
    if receipt.get("capture_run_id") != EXPECTED_CAPTURE_RUN_ID:
        raise Hz33DiagnosticError("capture run mismatch")
    if receipt.get("capture_artifact_id") != EXPECTED_CAPTURE_ARTIFACT_ID:
        raise Hz33DiagnosticError("capture artifact ID mismatch")
    if receipt.get("capture_artifact_digest_sha256") != EXPECTED_CAPTURE_DIGEST:
        raise Hz33DiagnosticError("capture artifact digest mismatch")
    if receipt.get("review_only") is not True or receipt.get("promotion_ready") is not False:
        raise Hz33DiagnosticError("receipt safety state mismatch")
    if any(receipt.get(key) is not False for key in (
        "parser_behavior_changed",
        "database_write_performed",
        "review_write_performed",
        "deployment_performed",
    )):
        raise Hz33DiagnosticError("receipt records a forbidden mutation")

    if adjudication.get("strategy") != EXPECTED_ADJUDICATION_STRATEGY:
        raise Hz33DiagnosticError("adjudication strategy mismatch")
    if adjudication.get("completed_source_truth_sha256") != EXPECTED_TRUTH_SHA256:
        raise Hz33DiagnosticError("adjudication truth SHA mismatch")
    if adjudication.get("review_only") is not True or adjudication.get("promotion_ready") is not False:
        raise Hz33DiagnosticError("adjudication safety state mismatch")
    if adjudication.get("metrics") != receipt.get("metrics"):
        raise Hz33DiagnosticError("adjudication metrics do not match receipt")
    if adjudication.get("acceptance") != receipt.get("acceptance"):
        raise Hz33DiagnosticError("acceptance contract does not match receipt")
    if adjudication.get("acceptance_checks") != receipt.get("acceptance_checks"):
        raise Hz33DiagnosticError("acceptance checks do not match receipt")
    if adjudication.get("acceptance_pass") != receipt.get("acceptance_pass"):
        raise Hz33DiagnosticError("acceptance result does not match receipt")

    rows = adjudication.get("rows")
    if not isinstance(rows, list) or not rows:
        raise Hz33DiagnosticError("adjudication rows are missing")

    primary_counts: Counter[str] = Counter()
    page_counts: dict[int, Counter[str]] = defaultdict(Counter)
    route_counts: Counter[str] = Counter()
    truth_counts: Counter[str] = Counter()
    diagnostic_rows: list[dict[str, Any]] = []
    cell_ids: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise Hz33DiagnosticError("adjudication row must be an object")
        cell_id = str(row.get("cell_id") or "")
        if not cell_id or cell_id in cell_ids:
            raise Hz33DiagnosticError("cell IDs must be non-empty and unique")
        cell_ids.add(cell_id)
        page = row.get("page_number")
        if not isinstance(page, int) or not (1 <= page <= 77):
            raise Hz33DiagnosticError(f"invalid page for {cell_id}")
        route = str(row.get("geometry_group_route") or "")
        truth_class = str(row.get("truth_class") or "")
        if route not in ALLOWED_ROUTES:
            raise Hz33DiagnosticError(f"unexpected route for {cell_id}: {route}")
        if truth_class not in ALLOWED_TRUTH:
            raise Hz33DiagnosticError(f"unexpected truth class for {cell_id}: {truth_class}")
        primary = _primary_class(truth_class, route)
        primary_counts[primary] += 1
        page_counts[page][primary] += 1
        route_counts[route] += 1
        truth_counts[truth_class] += 1
        diagnostic_rows.append(
            {
                "cell_id": cell_id,
                "page_number": page,
                "geometry_group_route": route,
                "truth_class": truth_class,
                "primary_diagnostic_class": primary,
                "unsafe_or_evidence_gap": primary in UNSAFE_PRIMARY,
                "in_scope_truth_ids": sorted(str(value) for value in row.get("in_scope_truth_ids", [])),
                "excluded_truth_ids": sorted(str(value) for value in row.get("excluded_truth_ids", [])),
                "group_ids": sorted(str(value) for value in row.get("group_ids", [])),
            }
        )

    if sum(primary_counts.values()) != len(rows):
        raise Hz33DiagnosticError("not every row received exactly one primary class")

    reuse_rows = adjudication.get("cross_cell_group_reuse_rows")
    if not isinstance(reuse_rows, list):
        raise Hz33DiagnosticError("cross-cell group reuse evidence is missing")
    secondary_reuse_cells = sorted(
        {
            str(cell_id)
            for reuse in reuse_rows
            if isinstance(reuse, Mapping)
            for cell_id in reuse.get("cell_ids", [])
        }
    )

    page_hotspots = []
    for page, counts in sorted(page_counts.items()):
        unsafe = sum(counts[name] for name in UNSAFE_PRIMARY)
        conservative = counts["conservative_review"]
        mixed_held = counts["mixed_held_review"]
        if unsafe or conservative or mixed_held:
            page_hotspots.append(
                {
                    "page_number": page,
                    "unsafe_or_evidence_gap": unsafe,
                    "conservative_review": conservative,
                    "mixed_held_review": mixed_held,
                    "primary_counts": dict(sorted(counts.items())),
                }
            )

    return {
        "schema_version": 1,
        "strategy": REPORT_STRATEGY,
        "adjudication_sha256": adjudication_sha,
        "completed_source_truth_sha256": EXPECTED_TRUTH_SHA256,
        "capture_run_id": EXPECTED_CAPTURE_RUN_ID,
        "capture_artifact_id": EXPECTED_CAPTURE_ARTIFACT_ID,
        "capture_artifact_digest_sha256": EXPECTED_CAPTURE_DIGEST,
        "frozen_acceptance": receipt["acceptance"],
        "frozen_acceptance_checks": receipt["acceptance_checks"],
        "frozen_acceptance_pass": receipt["acceptance_pass"],
        "row_count": len(rows),
        "primary_counts": dict(sorted(primary_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "truth_counts": dict(sorted(truth_counts.items())),
        "unsafe_or_evidence_gap_count": sum(primary_counts[name] for name in UNSAFE_PRIMARY),
        "conservative_review_count": primary_counts["conservative_review"],
        "mixed_held_review_count": primary_counts["mixed_held_review"],
        "cross_cell_group_reuse_count": len(reuse_rows),
        "cross_cell_group_reuse_cells": secondary_reuse_cells,
        "page_hotspots": page_hotspots,
        "rows": sorted(diagnostic_rows, key=lambda row: (row["page_number"], row["cell_id"])),
        "threshold_tuning_performed": False,
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
    parser = argparse.ArgumentParser(description="Classify committed hz33 held-out ownership disagreements without tuning")
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise Hz33DiagnosticError("diagnostic output must be create-only")
    report = diagnose(args.adjudication, args.receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(report))
    print(json.dumps({
        "frozen_acceptance_pass": report["frozen_acceptance_pass"],
        "row_count": report["row_count"],
        "unsafe_or_evidence_gap_count": report["unsafe_or_evidence_gap_count"],
        "conservative_review_count": report["conservative_review_count"],
        "mixed_held_review_count": report["mixed_held_review_count"],
        "cross_cell_group_reuse_count": report["cross_cell_group_reuse_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
