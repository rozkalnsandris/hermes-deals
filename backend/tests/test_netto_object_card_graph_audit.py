from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/netto_object_card_graph_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_object_card_graph_audit_tested",
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
        "spans": [],
        "vectors": {
            "horizontal_lines": [],
            "vertical_lines": [
                {
                    "x1": 50.0,
                    "y1": 10.0,
                    "x2": 50.0,
                    "y2": 90.0,
                    "length": 80.0,
                }
            ],
            "rectangles": [],
            "filled_rectangles": [],
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
                "bbox": {"x0": 20.0, "y0": 60.0, "x1": 32.0, "y1": 72.0},
            }
        ],
        "price_anchors": [
            {
                "anchor_id": "a001",
                "bbox": {"x0": 22.0, "y0": 61.0, "x1": 30.0, "y1": 70.0},
                "source_kind": "full",
                "member_labeled": False,
                "member_badge_ambiguous": False,
                "regular_labeled": False,
                "unit_labeled": False,
            }
        ],
    }


def page_objects() -> dict[str, object]:
    return {
        "page": {
            "width_points": 100.0,
            "height_points": 100.0,
            "page_number": 1,
            "rotation": 0,
        },
        "text_blocks": [
            {
                "object_type": "text_block",
                "object_id": "text-block:7",
                "block_number": 7,
                "bbox": {"x0": 18.0, "y0": 20.0, "x1": 45.0, "y1": 35.0},
                "text": "Left product",
            }
        ],
        "images": [
            {
                "object_type": "image",
                "object_id": "image:3:0",
                "number": 3,
                "bbox": {"x0": 15.0, "y0": 35.0, "x1": 42.0, "y1": 58.0},
                "width": 500,
                "height": 400,
                "xres": 96,
                "yres": 96,
                "bpc": 8,
                "colorspace": 3,
                "colorspace_name": "DeviceRGB",
                "xref": 42,
                "has_mask": False,
                "digest": "001122",
                "transform": [27.0, 0.0, 0.0, 23.0, 15.0, 35.0],
            }
        ],
        "image_binary_retained": False,
    }


def test_source_graph_extraction_is_truth_independent() -> None:
    signature = inspect.signature(MODULE.extract_fixture_object_graphs)
    assert list(signature.parameters) == [
        "fixture",
        "layout",
        "analysis",
        "page_objects",
        "geometry_module",
    ]
    assert "truth" not in signature.parameters
    assert "independent" not in signature.parameters


def test_text_block_metadata_preserves_number_bbox_and_text() -> None:
    rows = MODULE.normalize_text_blocks(
        [
            (10.0, 20.0, 30.0, 40.0, "  Product   title  ", 7, 0),
            (11.0, 21.0, 31.0, 41.0, "<image metadata>", 8, 1),
        ],
        GEOMETRY,
    )

    assert rows == [
        {
            "object_type": "text_block",
            "object_id": "text-block:7",
            "block_number": 7,
            "bbox": {"x0": 10.0, "y0": 20.0, "x1": 30.0, "y1": 40.0},
            "text": "Product title",
        }
    ]


def test_image_metadata_is_sanitized_without_binary_payload() -> None:
    rows = MODULE.sanitize_image_info(
        [
            {
                "number": 3,
                "bbox": (10.0, 20.0, 40.0, 50.0),
                "width": 640,
                "height": 480,
                "xres": 96,
                "yres": 96,
                "bpc": 8,
                "colorspace": 3,
                "cs-name": "DeviceRGB",
                "xref": 99,
                "has-mask": True,
                "digest": b"\x01\x02\x03",
                "transform": (30.0, 0.0, 0.0, 30.0, 10.0, 20.0),
                "image": b"forbidden-binary-payload",
            }
        ],
        GEOMETRY,
    )

    assert rows[0]["number"] == 3
    assert rows[0]["bbox"] == {"x0": 10.0, "y0": 20.0, "x1": 40.0, "y1": 50.0}
    assert rows[0]["digest"] == "010203"
    assert rows[0]["xref"] == 99
    assert "image" not in rows[0]
    assert b"forbidden-binary-payload" not in repr(rows[0]).encode()


def test_object_graph_preserves_block_image_group_and_anchor_provenance() -> None:
    row = MODULE.extract_fixture_object_graphs(
        fixture(),
        layout(),
        analysis(),
        page_objects(),
        GEOMETRY,
    )[0]

    assert row["node_type_counts"] == {
        "image": 1,
        "price_anchor": 1,
        "price_group": 1,
        "text_block": 1,
    }
    assert row["image_binary_retained"] is False
    nodes = {item["node_id"]: item for item in row["nodes"]}
    assert nodes["text-block:7"]["metadata"]["block_number"] == 7
    assert nodes["image:3:0"]["metadata"]["xref"] == 42
    assert nodes["price-group:g001"]["metadata"]["group_id"] == "g001"
    assert nodes["price-anchor:a001"]["metadata"]["source_kind"] == "full"


def test_graph_records_pairwise_relationships_and_two_component_views() -> None:
    row = MODULE.extract_fixture_object_graphs(
        fixture(),
        layout(),
        analysis(),
        page_objects(),
        GEOMETRY,
    )[0]

    assert len(row["pairwise_relations"]) == 6
    assert row["proximity_component_count"] >= 1
    assert row["separator_respecting_component_count"] >= 1
    assert all(
        "bbox_gap_fraction" in relation
        and "center_distance_fraction" in relation
        and "source_separator_between" in relation
        for relation in row["pairwise_relations"]
    )


def test_fixture_object_graph_is_deterministic() -> None:
    first = MODULE.extract_fixture_object_graphs(
        fixture(),
        layout(),
        analysis(),
        page_objects(),
        GEOMETRY,
    )
    second = MODULE.extract_fixture_object_graphs(
        fixture(),
        layout(),
        analysis(),
        page_objects(),
        GEOMETRY,
    )
    assert first == second


def test_truth_is_loaded_only_after_source_graph_freeze() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    source_freeze = source.index("source_rows.extend(")
    truth_load = source.index("truth = OWNERSHIP.load_ownership_truth")
    assert source_freeze < truth_load
    assert 'truth_use_contract": "adjudication_only_after_source_object_graph_freeze"' in source


def test_required_mixed_canaries_are_diagnostic_only() -> None:
    assert MODULE.MIXED_CANARY_CELL_IDS == (
        "2073a7926a2caacc0f257767",
        "b96e8863f348bd632f74db8f",
        "beea6693263e14fc6adca1c6",
        "aa0f536b410f09e7a217fbb1",
    )
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "MIXED_CANARY_CELL_IDS" in source
    assert "candidate_ownership_binding" not in source


# Keep the diagnostic contract explicit: this test must stay source-only/read-only.
def test_source_contract_forbids_parser_decision_ocr_or_writes() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert 'page.get_text("blocks", sort=False)' in source
    assert "page.get_image_info(hashes=True, xrefs=True)" in source
    assert '"image_binary_retained": False' in source
    assert '"ocr_used": False' in source
    assert '"classification_performed": False' in source
    assert '"parser_behavior_changed": False' in source
    assert '"promotion_ready": False' in source
    assert '"automatic_approval_enabled": False' in source
    assert '"automatic_publish_enabled": False' in source
    assert '"database_write_performed": False' in source
    assert '"deployment_performed": False' in source
    assert "get_textpage_ocr" not in source
