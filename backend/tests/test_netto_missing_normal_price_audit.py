from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_missing_normal_price_audit.py"
SPEC = importlib.util.spec_from_file_location("netto_missing_normal_price_audit_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def cell() -> dict[str, object]:
    return {
        "cell_id": "cell-1",
        "publication_slug": "hz32_hasb",
        "page_number": 42,
        "region_x0": 0.0,
        "region_y0": 0.0,
        "region_x1": 1.0,
        "region_y1": 1.0,
    }


def truth(price: str = "10.49") -> dict[str, object]:
    return {"expected_primary_price_eur": price}


def base_row(
    *,
    chosen: str | None = "g001",
    center: list[str] | None = None,
    intersecting: list[str] | None = None,
) -> dict[str, object]:
    return {
        "cell_id": "cell-1",
        "geometry_binding_state": "single_center_group" if chosen else "multiple_center_groups_review_required",
        "geometry_group_id": chosen,
        "center_group_ids": center if center is not None else ([chosen] if chosen else ["g001", "g002"]),
        "intersecting_group_ids": intersecting if intersecting is not None else ([chosen] if chosen else ["g001", "g002"]),
    }


def group(
    group_id: str,
    *,
    anchors: list[str] | None = None,
    normals: list[str] | None = None,
    members: list[str] | None = None,
    selected: str | None = None,
) -> dict[str, object]:
    return {
        "group_id": group_id,
        "bbox": {"x0": 10.0, "y0": 10.0, "x1": 90.0, "y1": 90.0},
        "anchor_ids": anchors or [],
        "normal_price_candidates": normals or [],
        "member_price_candidates": members or [],
        "selected_normal_price": selected,
    }


def anchor(anchor_id: str, value: str, *, source_kind: str = "full_decimal_span") -> dict[str, object]:
    return {
        "anchor_id": anchor_id,
        "value": value,
        "source_kind": source_kind,
        "bbox": {"x0": 40.0, "y0": 40.0, "x1": 60.0, "y1": 60.0},
    }


def analysis(groups: list[dict[str, object]], anchors: list[dict[str, object]]) -> dict[str, object]:
    return {
        "page": {"width_points": 100.0, "height_points": 100.0, "page_number": 42},
        "groups": groups,
        "price_anchors": anchors,
    }


def test_absent_expected_anchor_is_classified_before_ownership_guessing() -> None:
    result = MODULE.diagnose_cell(
        cell(),
        truth(),
        base_row(),
        analysis([group("g001", normals=["9.99"], selected="9.99")], [anchor("a1", "9.99")]),
    )
    assert result["diagnostic_cause"] == "expected_anchor_absent_in_cell"
    assert result["expected_anchor_ids_in_cell"] == []
    assert result["review_only"] is True
    assert result["promotion_ready"] is False


def test_present_anchor_without_group_assignment_is_distinct_from_extraction_failure() -> None:
    result = MODULE.diagnose_cell(
        cell(),
        truth(),
        base_row(),
        analysis([group("g001", normals=["9.99"], selected="9.99")], [anchor("a1049", "10.49")]),
    )
    assert result["diagnostic_cause"] == "expected_anchor_unassigned_to_group"
    assert result["expected_anchor_ids_in_cell"] == ["a1049"]
    assert result["expected_anchor_group_ids"] == []


def test_unresolved_multi_group_binding_stays_fail_closed() -> None:
    result = MODULE.diagnose_cell(
        cell(),
        truth(),
        base_row(chosen=None),
        analysis(
            [
                group("g001", anchors=["a1049"], normals=["10.49"]),
                group("g002", anchors=["a999"], members=["9.99"]),
            ],
            [anchor("a1049", "10.49"), anchor("a999", "9.99")],
        ),
    )
    assert result["diagnostic_cause"] == "expected_anchor_present_binding_unresolved"
    assert result["center_group_normal_price_candidates"] == ["10.49"]
    assert result["center_group_member_price_candidates"] == ["9.99"]


def test_member_typed_expected_anchor_is_not_relabelled_as_normal() -> None:
    result = MODULE.diagnose_cell(
        cell(),
        truth(),
        base_row(),
        analysis(
            [group("g001", anchors=["a1049"], members=["10.49"], selected=None)],
            [anchor("a1049", "10.49")],
        ),
    )
    assert result["diagnostic_cause"] == "expected_anchor_typed_member"
    assert result["center_group_member_price_candidates"] == ["10.49"]


def test_normal_candidate_present_but_unselected_has_own_cause() -> None:
    result = MODULE.diagnose_cell(
        cell(),
        truth(),
        base_row(),
        analysis(
            [group("g001", anchors=["a1049", "a999"], normals=["10.49", "9.99"], selected=None)],
            [anchor("a1049", "10.49"), anchor("a999", "9.99")],
        ),
    )
    assert result["diagnostic_cause"] == "expected_normal_candidate_not_selected"
    assert result["expected_anchor_group_ids"] == ["g001"]


def test_exact_selected_normal_price_is_control_match() -> None:
    result = MODULE.diagnose_cell(
        cell(),
        truth(),
        base_row(),
        analysis(
            [group("g001", anchors=["a1049"], normals=["10.49"], selected="10.49")],
            [anchor("a1049", "10.49", source_kind="split_major_cents")],
        ),
    )
    assert result["diagnostic_cause"] == "selected_normal_price_match"
    assert result["selected_normal_price"] == "10.49"
    assert result["expected_anchor_source_kinds"] == {"a1049": "split_major_cents"}
