from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_heldout_hz33_adjudication.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_hz33_adjudication", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _truth_page() -> tuple[dict, list[dict]]:
    regions: list[dict] = []
    predictions: list[dict] = []
    cursor = 20.0

    # 50 unambiguous in-scope single-source cells. These are the only
    # auto-single rows in the passing fixture, so precision is exactly 1.0.
    for index in range(50):
        region_id = f"single-{index:03d}"
        rect = [cursor, 20.0, cursor + 40.0, 80.0]
        regions.append(
            {
                "source_region_id": region_id,
                "rect_points": rect,
                "source_scope": "in_scope",
                "boundary_state": "clear_single_card",
                "reviewer_confidence": "high",
            }
        )
        predictions.append(
            {
                "page_number": 1,
                "cell_id": f"cell-single-{index:03d}",
                "rect_points": rect,
                "geometry_group_route": "single_center_group",
                "group_id": f"g-single-{index:03d}",
            }
        )
        cursor += 60.0

    # Exactly five held-out mixed-source cells, each spanning two independently
    # reviewed in-scope source regions. They remain on the Review-only route.
    for index in range(5):
        left = [cursor, 20.0, cursor + 35.0, 80.0]
        right = [cursor + 35.0, 20.0, cursor + 70.0, 80.0]
        regions.extend(
            [
                {
                    "source_region_id": f"mixed-{index:03d}-a",
                    "rect_points": left,
                    "source_scope": "in_scope",
                    "boundary_state": "clear_single_card",
                    "reviewer_confidence": "high",
                },
                {
                    "source_region_id": f"mixed-{index:03d}-b",
                    "rect_points": right,
                    "source_scope": "in_scope",
                    "boundary_state": "clear_single_card",
                    "reviewer_confidence": "high",
                },
            ]
        )
        predictions.append(
            {
                "page_number": 1,
                "cell_id": f"cell-mixed-{index:03d}",
                "rect_points": [cursor, 20.0, cursor + 70.0, 80.0],
                "geometry_group_route": "multiple_center_groups_review_required",
                "group_id": f"g-mixed-{index:03d}",
            }
        )
        cursor += 90.0

    # Five excluded controls must never become auto-single eligible.
    for index in range(5):
        rect = [cursor, 20.0, cursor + 40.0, 80.0]
        regions.append(
            {
                "source_region_id": f"excluded-{index:03d}",
                "rect_points": rect,
                "source_scope": "excluded_non_target",
                "boundary_state": "clear_single_card",
                "reviewer_confidence": "high",
            }
        )
        predictions.append(
            {
                "page_number": 1,
                "cell_id": f"cell-excluded-{index:03d}",
                "rect_points": rect,
                "geometry_group_route": "excluded_control",
                "group_id": f"g-excluded-{index:03d}",
            }
        )
        cursor += 60.0

    return {
        "page_number": 1,
        "page_width_points": 5000.0,
        "page_height_points": 1000.0,
        "source_regions": regions,
    }, predictions


def _truth_and_predictions() -> tuple[dict, dict]:
    first_page, predictions = _truth_page()
    pages = [first_page]
    for page_number in range(2, 78):
        pages.append(
            {
                "page_number": page_number,
                "page_width_points": 1000.0,
                "page_height_points": 1000.0,
                "source_regions": [],
            }
        )
    truth = {
        "schema_version": 1,
        "campaign_key": "hz33_hasb",
        "source_sha256": "1" * 64,
        "freeze_manifest_sha256": "4" * 64,
        "pages": pages,
    }
    prediction_payload = {
        "schema_version": 1,
        "coordinate_space": "unrotated_page_points",
        "records": predictions,
    }
    return truth, prediction_payload


def _install_bindings(monkeypatch: pytest.MonkeyPatch, truth: dict, predictions_sha: str) -> None:
    truth_plain = json.dumps(truth, sort_keys=True).encode("utf-8")
    monkeypatch.setattr(MODULE, "EXPECTED_COMPLETED_SHA256", MODULE.hashlib.sha256(truth_plain).hexdigest())
    monkeypatch.setattr(
        MODULE,
        "validate_completed_truth_file",
        lambda _path: ({"completed_source_truth_sha256": MODULE.EXPECTED_COMPLETED_SHA256}, truth_plain),
    )
    freeze = {
        "campaign_key": "hz33_hasb",
        "source_sha256": "1" * 64,
        "predictions_sha256": predictions_sha,
    }
    receipt = {
        "predictions_sha256": predictions_sha,
        "freeze_manifest_sha256": "4" * 64,
        "truth_available_at_freeze": False,
    }
    monkeypatch.setattr(MODULE, "validate_freeze_manifest", lambda _payload: freeze)
    monkeypatch.setattr(MODULE, "validate_freeze_receipt", lambda _freeze, _receipt: None)
    monkeypatch.setattr(MODULE, "file_sha256", lambda _path, _label: predictions_sha)
    monkeypatch.setattr(MODULE, "_load_json", lambda path, label: receipt if "receipt" in label else (json.loads(path.read_text()) if "predictions" in label else {}))


def test_spatial_adjudication_passes_all_frozen_thresholds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    truth, predictions = _truth_and_predictions()
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
    predictions_sha = "a" * 64
    _install_bindings(monkeypatch, truth, predictions_sha)

    result = MODULE.adjudicate(
        completed_truth_path=tmp_path / "truth.json.gz",
        predictions_path=predictions_path,
        freeze_manifest_path=tmp_path / "freeze-manifest.json",
        freeze_receipt_path=tmp_path / "freeze-receipt.json",
    )

    metrics = result["metrics"]
    assert metrics["prediction_records"] == 60
    assert metrics["reviewed_cells"] == 60
    assert metrics["single_source_cells"] == 50
    assert metrics["mixed_source_cells"] == 5
    assert metrics["excluded_control_cells"] == 5
    assert metrics["unmatched_review_required"] == 0
    assert metrics["scope_overlap_review_required"] == 0
    assert metrics["auto_single_count"] == 50
    assert metrics["auto_single_true_positive"] == 50
    assert metrics["auto_single_false_positive"] == 0
    assert metrics["auto_single_precision"] == 1.0
    assert metrics["mixed_source_auto_single"] == 0
    assert metrics["excluded_control_auto_eligible"] == 0
    assert metrics["cross_cell_group_reuse"] == 0
    assert all(result["acceptance_checks"].values())
    assert result["acceptance_pass"] is True
    assert result["review_only"] is True
    assert result["promotion_ready"] is False


def test_spatial_adjudication_marks_unmatched_and_scope_overlap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    truth, predictions = _truth_and_predictions()
    predictions["records"] = [
        {
            "page_number": 1,
            "cell_id": "cell-unmatched",
            "rect_points": [4900.0, 200.0, 4950.0, 250.0],
            "geometry_group_route": "multiple_center_groups_review_required",
        },
        {
            "page_number": 1,
            "cell_id": "cell-scope-overlap",
            "rect_points": [20.0, 20.0, 3100.0, 80.0],
            "geometry_group_route": "multiple_center_groups_review_required",
        },
    ]
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
    _install_bindings(monkeypatch, truth, "b" * 64)

    result = MODULE.adjudicate(
        completed_truth_path=tmp_path / "truth.json.gz",
        predictions_path=predictions_path,
        freeze_manifest_path=tmp_path / "freeze-manifest.json",
        freeze_receipt_path=tmp_path / "freeze-receipt.json",
    )
    by_id = {row["cell_id"]: row for row in result["rows"]}
    assert by_id["cell-unmatched"]["truth_class"] == "unmatched_review_required"
    assert by_id["cell-scope-overlap"]["truth_class"] == "scope_overlap_review_required"


def test_mixed_auto_single_fails_frozen_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    truth, predictions = _truth_and_predictions()
    for row in predictions["records"]:
        if row["cell_id"] == "cell-mixed-000":
            row["geometry_group_route"] = "single_center_group"
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
    _install_bindings(monkeypatch, truth, "c" * 64)

    result = MODULE.adjudicate(
        completed_truth_path=tmp_path / "truth.json.gz",
        predictions_path=predictions_path,
        freeze_manifest_path=tmp_path / "freeze-manifest.json",
        freeze_receipt_path=tmp_path / "freeze-receipt.json",
    )
    assert result["metrics"]["mixed_source_auto_single"] == 1
    assert result["acceptance_checks"]["maximum_mixed_source_auto_single"] is False
    assert result["acceptance_pass"] is False


def test_cross_cell_group_reuse_fails_frozen_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    truth, predictions = _truth_and_predictions()
    predictions["records"][0]["group_id"] = "shared"
    predictions["records"][1]["group_id"] = "shared"
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
    _install_bindings(monkeypatch, truth, "d" * 64)

    result = MODULE.adjudicate(
        completed_truth_path=tmp_path / "truth.json.gz",
        predictions_path=predictions_path,
        freeze_manifest_path=tmp_path / "freeze-manifest.json",
        freeze_receipt_path=tmp_path / "freeze-receipt.json",
    )
    assert result["metrics"]["cross_cell_group_reuse"] == 1
    assert result["acceptance_checks"]["maximum_cross_cell_group_reuse"] is False
    assert result["acceptance_pass"] is False


def test_adjudicator_does_not_use_product_title_or_price_semantics() -> None:
    source = TOOL.read_text(encoding="utf-8").lower()
    assert "expected_title" not in source
    assert "selected_title" not in source
    assert "expected_price" not in source
    assert "selected_price" not in source
    assert "n10" not in source
