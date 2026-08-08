from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/netto_card_region_topology_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_card_region_topology_audit_tested",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

GEOMETRY = MODULE.BASE.load_geometry_module()


def fixture() -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_id": "cell-1",
                "publication_slug": "hz31_hasb_4",
                "page_number": 1,
                "scope_state": "target_or_review_card",
                "region_x0": 0.1,
                "region_y0": 0.1,
                "region_x1": 0.9,
                "region_y1": 0.9,
            }
        ]
    }


def layout() -> dict[str, object]:
    return {
        "page": {
            "width_points": 100.0,
            "height_points": 100.0,
            "page_number": 1,
            "rotation": 0,
        },
        "spans": [
            {
                "text": "Left product",
                "bbox": [20.0, 20.0, 35.0, 30.0],
                "size": 10.0,
                "font": "Test",
                "color": 0,
                "flags": 0,
            },
            {
                "text": "Right product",
                "bbox": [65.0, 20.0, 80.0, 30.0],
                "size": 10.0,
                "font": "Test",
                "color": 0,
                "flags": 0,
            },
            {
                "text": "1.99",
                "bbox": [20.0, 60.0, 32.0, 70.0],
                "size": 16.0,
                "font": "Test",
                "color": 0,
                "flags": 0,
            },
        ],
        "vectors": {
            "horizontal_lines": [
                {
                    "x1": 0.0,
                    "y1": 50.0,
                    "x2": 100.0,
                    "y2": 50.0,
                    "length": 100.0,
                },
                {
                    "x1": 10.0,
                    "y1": 10.0,
                    "x2": 90.0,
                    "y2": 10.0,
                    "length": 80.0,
                },
            ],
            "vertical_lines": [
                {
                    "x1": 50.0,
                    "y1": 20.0,
                    "x2": 50.0,
                    "y2": 80.0,
                    "length": 60.0,
                }
            ],
            "rectangles": [
                {"x0": 15.0, "y0": 15.0, "x1": 85.0, "y1": 85.0}
            ],
            "filled_rectangles": [
                {
                    "x0": 18.0,
                    "y0": 58.0,
                    "x1": 34.0,
                    "y1": 72.0,
                    "fill_rgb": [220, 13, 21],
                    "fill_opacity": 1.0,
                    "seqno": 1,
                }
            ],
        },
    }


def analysis() -> dict[str, object]:
    return {
        "page": {
            "width_points": 100.0,
            "height_points": 100.0,
            "page_number": 1,
            "rotation": 0,
        },
        "groups": [
            {
                "group_id": "g001",
                "bbox": {"x0": 18.0, "y0": 58.0, "x1": 34.0, "y1": 72.0},
            },
            {
                "group_id": "g002",
                "bbox": {"x0": 65.0, "y0": 58.0, "x1": 80.0, "y1": 72.0},
            },
        ],
    }


def test_topology_extraction_is_truth_independent() -> None:
    signature = inspect.signature(MODULE.extract_fixture_topology)
    assert list(signature.parameters) == [
        "fixture",
        "layout",
        "analysis",
        "geometry_module",
    ]
    assert "truth" not in signature.parameters
    assert "independent" not in signature.parameters


def test_topology_records_multi_threshold_interior_cut_coverage() -> None:
    row = MODULE.extract_fixture_topology(
        fixture(),
        layout(),
        analysis(),
        GEOMETRY,
    )[0]

    assert row["center_group_ids"] == ["g001", "g002"]
    assert row["center_group_count"] == 2
    assert row["text_span_count"] == 3
    assert row["nonprice_text_span_count"] == 2

    horizontal = row["horizontal_cut_summary"]
    assert horizontal["interior_vector_count"] == 1
    assert horizontal["strongest_interior_coverage"] == 1.0
    assert horizontal["strongest_interior_position"] == 0.5
    assert horizontal["coverage_threshold_counts"] == {
        "ge_35": 1,
        "ge_50": 1,
        "ge_70": 1,
        "ge_85": 1,
    }

    vertical = row["vertical_cut_summary"]
    assert vertical["interior_vector_count"] == 1
    assert vertical["strongest_interior_coverage"] == 0.75
    assert vertical["strongest_interior_position"] == 0.5
    assert vertical["coverage_threshold_counts"] == {
        "ge_35": 1,
        "ge_50": 1,
        "ge_70": 1,
        "ge_85": 0,
    }


def test_boundary_vector_is_preserved_but_not_counted_as_interior_cut() -> None:
    row = MODULE.extract_fixture_topology(
        fixture(),
        layout(),
        analysis(),
        GEOMETRY,
    )[0]
    horizontal = row["horizontal_vector_evidence"]
    assert len(horizontal) == 2
    assert any(item["position"] == 0.0 and item["interior"] is False for item in horizontal)
    assert row["horizontal_cut_summary"]["interior_vector_count"] == 1


def test_topology_records_content_sides_quadrants_and_rectangles() -> None:
    row = MODULE.extract_fixture_topology(
        fixture(),
        layout(),
        analysis(),
        GEOMETRY,
    )[0]

    assert row["content_point_count"] == 5
    assert row["content_quadrant_counts"] == {
        "top_left": 1,
        "top_right": 1,
        "bottom_left": 2,
        "bottom_right": 1,
    }
    assert row["strongest_vertical_cut_side_occupancy"] == {
        "before": 3,
        "after": 2,
        "near": 0,
    }
    assert row["strongest_horizontal_cut_side_occupancy"] == {
        "before": 2,
        "after": 3,
        "near": 0,
    }
    assert len(row["rectangle_evidence"]) == 1
    assert row["rectangle_evidence"][0]["contains_cell_center"] is True
    assert len(row["filled_rectangle_evidence"]) == 1
    assert row["filled_rectangle_evidence"][0]["fill_rgb"] == [220, 13, 21]
    assert row["review_only"] is True
    assert row["promotion_ready"] is False


def test_topology_summary_compares_distributions_without_classifying_cells() -> None:
    rows = [
        {
            "independent_ownership": "single_source",
            "center_group_count": 1,
            "text_span_count": 4,
            "nonprice_text_span_count": 3,
            "horizontal_cut_summary": {"strongest_interior_coverage": 0.1},
            "vertical_cut_summary": {"strongest_interior_coverage": 0.2},
        },
        {
            "independent_ownership": "single_source",
            "center_group_count": 2,
            "text_span_count": 8,
            "nonprice_text_span_count": 6,
            "horizontal_cut_summary": {"strongest_interior_coverage": 0.8},
            "vertical_cut_summary": {"strongest_interior_coverage": 0.1},
        },
        {
            "independent_ownership": "mixed_source",
            "center_group_count": 1,
            "text_span_count": 10,
            "nonprice_text_span_count": 8,
            "horizontal_cut_summary": {"strongest_interior_coverage": 0.6},
            "vertical_cut_summary": {"strongest_interior_coverage": 0.9},
        },
    ]

    summary = MODULE.summarize_topology(rows)

    assert summary["single_source"]["cell_count"] == 2
    assert summary["single_source"]["center_group_count_histogram"] == {"1": 1, "2": 1}
    assert summary["single_source"]["text_span_count_median"] == 6.0
    assert summary["single_source"]["either_orientation_cut_cell_counts"] == {
        "ge_35": 1,
        "ge_50": 1,
        "ge_70": 1,
        "ge_85": 0,
    }
    assert summary["mixed_source"]["cell_count"] == 1
    assert summary["mixed_source"]["either_orientation_cut_cell_counts"] == {
        "ge_35": 1,
        "ge_50": 1,
        "ge_70": 1,
        "ge_85": 1,
    }


def test_source_contract_forbids_parser_decision_or_writes() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert '"classification_performed": False' in source
    assert '"parser_behavior_changed": False' in source
    assert '"promotion_ready": False' in source
    assert '"automatic_approval_enabled": False' in source
    assert '"automatic_publish_enabled": False' in source
    assert '"database_write_performed": False' in source
    assert '"deployment_performed": False' in source
    assert "candidate_ownership_binding" not in source
