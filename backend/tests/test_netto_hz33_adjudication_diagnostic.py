from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_hz33_adjudication_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("netto_hz33_adjudication_diagnostic", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row(index: int, truth: str, route: str, *, group_ids: list[str] | None = None) -> dict:
    return {
        "cell_id": f"cell-{index:02d}",
        "page_number": 1 + (index % 3),
        "geometry_group_route": route,
        "truth_class": truth,
        "in_scope_truth_ids": [f"truth-{index}"] if truth in {"single_source", "mixed_source", "scope_overlap_review_required"} else [],
        "excluded_truth_ids": [f"excluded-{index}"] if truth in {"excluded_control", "scope_overlap_review_required"} else [],
        "group_ids": group_ids or [],
    }


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    rows = [
        _row(0, "unmatched_review_required", "multiple_center_groups_review_required"),
        _row(1, "scope_overlap_review_required", "multiple_center_groups_review_required"),
        _row(2, "mixed_source", "single_center_group"),
        _row(3, "excluded_control", "single_center_group"),
        _row(4, "excluded_control", "multiple_center_groups_review_required"),
        _row(5, "single_source", "excluded_control"),
        _row(6, "mixed_source", "excluded_control"),
        _row(7, "single_source", "multiple_center_groups_review_required"),
        _row(8, "mixed_source", "multiple_center_groups_review_required"),
        _row(9, "single_source", "single_center_group", group_ids=["shared"]),
        _row(10, "excluded_control", "excluded_control", group_ids=["shared"]),
    ]
    acceptance = {
        "minimum_reviewed_cells": 50,
        "minimum_mixed_source_cells": 5,
        "maximum_mixed_source_auto_single": 0,
        "maximum_excluded_control_auto_eligible": 0,
        "minimum_auto_single_precision": 0.98,
        "maximum_cross_cell_group_reuse": 0,
    }
    checks = {key: False for key in acceptance}
    metrics = {"reviewed_cells": 9, "mixed_source_cells": 3}
    adjudication = {
        "schema_version": 1,
        "strategy": MODULE.EXPECTED_ADJUDICATION_STRATEGY,
        "completed_source_truth_sha256": MODULE.EXPECTED_TRUTH_SHA256,
        "acceptance": acceptance,
        "acceptance_checks": checks,
        "acceptance_pass": False,
        "metrics": metrics,
        "rows": rows,
        "cross_cell_group_reuse_rows": [
            {"page_number": 2, "group_id": "shared", "cell_ids": ["cell-09", "cell-10"]}
        ],
        "review_only": True,
        "promotion_ready": False,
    }
    adjudication_path = tmp_path / "adjudication.json"
    adjudication_path.write_text(json.dumps(adjudication, sort_keys=True), encoding="utf-8")
    raw = adjudication_path.read_bytes()
    receipt = {
        "schema_version": 1,
        "strategy": MODULE.EXPECTED_RECEIPT_STRATEGY,
        "capture_run_id": MODULE.EXPECTED_CAPTURE_RUN_ID,
        "capture_artifact_id": MODULE.EXPECTED_CAPTURE_ARTIFACT_ID,
        "capture_artifact_digest_sha256": MODULE.EXPECTED_CAPTURE_DIGEST,
        "completed_source_truth_sha256": MODULE.EXPECTED_TRUTH_SHA256,
        "adjudication_sha256": hashlib.sha256(raw).hexdigest(),
        "acceptance": acceptance,
        "metrics": metrics,
        "acceptance_checks": checks,
        "acceptance_pass": False,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return adjudication_path, receipt_path


def test_every_row_gets_exactly_one_primary_class(tmp_path: Path) -> None:
    adjudication, receipt = _write_fixture(tmp_path)
    report = MODULE.diagnose(adjudication, receipt)
    by_cell = {row["cell_id"]: row["primary_diagnostic_class"] for row in report["rows"]}
    assert by_cell == {
        "cell-00": "unmatched_evidence_gap",
        "cell-01": "scope_overlap_evidence_gap",
        "cell-02": "unsafe_auto_single",
        "cell-03": "unsafe_auto_single",
        "cell-04": "missed_excluded",
        "cell-05": "over_excluded",
        "cell-06": "over_excluded",
        "cell-07": "conservative_review",
        "cell-08": "mixed_held_review",
        "cell-09": "correct_auto_single",
        "cell-10": "correct_excluded_control",
    }
    assert sum(report["primary_counts"].values()) == report["row_count"] == 11
    assert report["unsafe_or_evidence_gap_count"] == 7
    assert report["conservative_review_count"] == 1
    assert report["mixed_held_review_count"] == 1
    assert report["cross_cell_group_reuse_count"] == 1
    assert report["cross_cell_group_reuse_cells"] == ["cell-09", "cell-10"]
    assert report["threshold_tuning_performed"] is False
    assert report["promotion_ready"] is False


def test_adjudication_hash_must_match_receipt(tmp_path: Path) -> None:
    adjudication, receipt = _write_fixture(tmp_path)
    payload = json.loads(adjudication.read_text(encoding="utf-8"))
    payload["rows"][0]["cell_id"] = "tampered"
    adjudication.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(MODULE.Hz33DiagnosticError, match="adjudication SHA"):
        MODULE.diagnose(adjudication, receipt)


def test_receipt_safety_mutation_is_rejected(tmp_path: Path) -> None:
    adjudication, receipt = _write_fixture(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["parser_behavior_changed"] = True
    receipt.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(MODULE.Hz33DiagnosticError, match="forbidden mutation"):
        MODULE.diagnose(adjudication, receipt)


def test_diagnostic_does_not_use_product_title_price_or_old_truth_semantics() -> None:
    source = TOOL.read_text(encoding="utf-8").lower()
    for forbidden in ("expected_title", "selected_title", "expected_price", "selected_price", "n9", "n10"):
        assert forbidden not in source
