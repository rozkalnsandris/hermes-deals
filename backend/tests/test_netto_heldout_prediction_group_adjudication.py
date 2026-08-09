from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_heldout_prediction_group_adjudication import (  # noqa: E402
    EXPECTED_ACCEPTANCE,
    adjudicate_group,
    build_metrics,
)
from netto_heldout_ownership_protocol import ACCEPTANCE  # noqa: E402


def region(region_id: str, rect: list[float], scope: str = "in_scope") -> dict:
    return {
        "source_region_id": region_id,
        "rect_points": rect,
        "scope_classification": scope,
    }


def group(
    *,
    title: list[int] | None = None,
    ambiguous: list[int] | None = None,
    anchors: list[str] | None = None,
    production_eligible: bool = False,
) -> dict:
    return {
        "group_id": "g001",
        "title_span_indexes": title or [],
        "ambiguous_span_indexes": ambiguous or [],
        "anchor_ids": anchors or [],
        "route": "review_required" if not production_eligible else "automatic_candidate",
        "production_eligible": production_eligible,
    }


def test_atom_center_maps_one_source_region_to_single_source() -> None:
    row = adjudicate_group(
        page_number=1,
        group=group(title=[0], anchors=["a1"]),
        spans={0: {"bbox": [10, 10, 20, 20]}},
        anchors={"a1": {"bbox": [30, 30, 40, 40]}},
        source_regions=[region("p001-r001", [0, 0, 50, 50])],
    )
    assert row["outcome"] == "single_source"
    assert row["in_scope_source_region_ids"] == ["p001-r001"]
    assert row["unmatched_atom_ids"] == []


def test_atom_center_across_two_in_scope_regions_is_mixed_source() -> None:
    row = adjudicate_group(
        page_number=1,
        group=group(title=[0], ambiguous=[1]),
        spans={
            0: {"bbox": [10, 10, 20, 20]},
            1: {"bbox": [60, 10, 70, 20]},
        },
        anchors={},
        source_regions=[
            region("p001-r001", [0, 0, 50, 50]),
            region("p001-r002", [50, 0, 100, 50]),
        ],
    )
    assert row["outcome"] == "mixed_source"
    assert row["in_scope_source_region_ids"] == ["p001-r001", "p001-r002"]


def test_atom_center_only_in_excluded_region_is_excluded_control() -> None:
    row = adjudicate_group(
        page_number=1,
        group=group(anchors=["a1"]),
        spans={},
        anchors={"a1": {"bbox": [10, 10, 20, 20]}},
        source_regions=[region("p001-r001", [0, 0, 50, 50], "excluded_non_target")],
    )
    assert row["outcome"] == "excluded_control"


def test_atom_center_cross_scope_fails_closed() -> None:
    row = adjudicate_group(
        page_number=1,
        group=group(title=[0], anchors=["a1"]),
        spans={0: {"bbox": [10, 10, 20, 20]}},
        anchors={"a1": {"bbox": [60, 10, 70, 20]}},
        source_regions=[
            region("p001-r001", [0, 0, 50, 50]),
            region("p001-r002", [50, 0, 100, 50], "excluded_non_target"),
        ],
    )
    assert row["outcome"] == "unresolved_cross_scope"


def test_unmapped_atom_fails_closed() -> None:
    row = adjudicate_group(
        page_number=1,
        group=group(title=[0]),
        spans={0: {"bbox": [110, 10, 120, 20]}},
        anchors={},
        source_regions=[region("p001-r001", [0, 0, 50, 50])],
    )
    assert row["outcome"] == "unresolved_unmapped_atoms"
    assert row["unmatched_atom_ids"] == ["span:0"]


def test_half_open_shared_edge_is_deterministic() -> None:
    # Center x=50 lies on the shared edge, so the half-open contract maps it
    # only to the right-hand region and never requires a tolerance.
    row = adjudicate_group(
        page_number=1,
        group=group(title=[0]),
        spans={0: {"bbox": [45, 10, 55, 20]}},
        anchors={},
        source_regions=[
            region("p001-r001", [0, 0, 50, 50]),
            region("p001-r002", [50, 0, 100, 50]),
        ],
    )
    assert row["outcome"] == "single_source"
    assert row["in_scope_source_region_ids"] == ["p001-r002"]


def metric_row(outcome: str, *, automatic: bool = False, index: int = 1) -> dict:
    return {
        "prediction_unit_id": f"p001-g{index:03d}",
        "outcome": outcome,
        "frozen_production_eligible": automatic,
    }


def test_metric_contract_preserves_predeclared_thresholds_and_not_evaluable_gates() -> None:
    assert ACCEPTANCE == EXPECTED_ACCEPTANCE
    rows = [metric_row("single_source", index=index) for index in range(1, 51)]
    rows += [metric_row("mixed_source", index=50 + index) for index in range(1, 6)]
    metrics, overall = build_metrics(rows)
    assert metrics["minimum_reviewed_cells"]["status"] == "PASS"
    assert metrics["minimum_mixed_source_cells"]["status"] == "PASS"
    assert metrics["maximum_mixed_source_auto_single"]["status"] == "PASS"
    assert metrics["maximum_excluded_control_auto_eligible"]["status"] == "PASS"
    assert metrics["minimum_auto_single_precision"]["status"] == "NOT_EVALUABLE"
    assert metrics["minimum_auto_single_precision"]["observed"] is None
    assert metrics["maximum_cross_cell_group_reuse"]["status"] == "NOT_EVALUABLE"
    assert overall is False


def test_literal_automatic_mixed_source_fails_zero_tolerance_gate() -> None:
    rows = [
        metric_row("single_source", automatic=True, index=1),
        metric_row("mixed_source", automatic=True, index=2),
    ]
    metrics, overall = build_metrics(rows)
    assert metrics["maximum_mixed_source_auto_single"]["status"] == "FAIL"
    assert metrics["maximum_mixed_source_auto_single"]["observed"] == 1
    assert metrics["minimum_auto_single_precision"]["observed"] == 0.5
    assert overall is False


def test_adjudicator_source_does_not_use_product_or_price_semantics_for_truth_mapping() -> None:
    source = (TOOLS / "netto_heldout_prediction_group_adjudication.py").read_text(encoding="utf-8")
    assert "title_span_indexes" in source
    assert "ambiguous_span_indexes" in source
    assert "anchor_ids" in source
    assert "_region_for_center" in source
    for forbidden in (
        "expected_title",
        "expected_primary_price_eur",
        "selected_title",
        "selected_normal_price",
        "product override",
        "campaign override",
    ):
        assert forbidden not in source
