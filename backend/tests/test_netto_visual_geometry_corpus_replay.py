from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_visual_geometry_corpus_replay.py"
SPEC = importlib.util.spec_from_file_location("netto_visual_geometry_corpus_replay_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_cell(cell_id: str, campaign: str, page: int, x0: float, x1: float, *, excluded: bool = False):
    return {
        "cell_id": cell_id,
        "publication_slug": campaign,
        "page_number": page,
        "review_state": "pending_visual_validation",
        "automatic_approval_allowed": False,
        "automatic_publish_allowed": False,
        "scope_state": "excluded_non_target_card" if excluded else "target_or_review_card",
        "region_x0": x0,
        "region_y0": 0.0,
        "region_x1": x1,
        "region_y1": 1.0,
    }


def make_fixture(campaign: str, page: int, cells):
    return {
        "schema_version": 1,
        "strategy": "netto_n9_n8_v2_visual_cell_fixture_v1",
        "review_state": "pending_visual_validation",
        "automatic_approval_count": 0,
        "automatic_publish_count": 0,
        "production_write_performed": False,
        "page": {
            "publication_slug": campaign,
            "page_number": page,
            "raw_cell_count": len(cells),
        },
        "cells": cells,
    }


def make_truth(cell_id: str, campaign: str, page: int, title: str, price: str):
    return {
        "cell_id": cell_id,
        "publication_slug": campaign,
        "page_number": page,
        "expected_title": title,
        "expected_primary_price_eur": price,
        "automatic_approval_allowed": False,
        "automatic_publish_allowed": False,
    }


def make_group(group_id: str, x0: float, x1: float, title: str, price: str, *, route: str = "automatic_candidate"):
    return {
        "group_id": group_id,
        "bbox": {"x0": x0, "y0": 20.0, "x1": x1, "y1": 80.0},
        "selected_title": title,
        "selected_normal_price": price,
        "route": route,
    }


def test_cell_rect_uses_unrotated_page_dimensions_only():
    cell = make_cell("c", "hz31_hasb_4", 14, 0.25, 0.75)
    assert MODULE.cell_rect(cell, 200.0, 400.0) == (50.0, 0.0, 150.0, 400.0)


def test_single_center_group_is_bound_then_compared_to_n10_truth():
    cells = [make_cell("c1", "hz31_hasb_4", 14, 0.0, 0.5)]
    fixture = make_fixture("hz31_hasb_4", 14, cells)
    analysis = {
        "page": {"width_points": 200.0, "height_points": 100.0, "page_number": 14, "rotation": 0},
        "groups": [make_group("g001", 20.0, 80.0, "Hohes C Vitamin Water", "1.19")],
    }
    truth = {"c1": make_truth("c1", "hz31_hasb_4", 14, "Hohes C Vitamin Water", "1.19")}
    row = MODULE.map_fixture(fixture, analysis, truth)[0]
    assert row["geometry_binding_state"] == "single_center_group"
    assert row["geometry_group_id"] == "g001"
    assert row["truth_comparison_state"] == "reproduced_match"
    assert row["title_exact_match"] is True
    assert row["normal_price_match"] is True
    assert row["promotion_ready"] is False


def test_title_comparison_normalizes_punctuation_without_hiding_price_drift():
    cells = [make_cell("c1", "hz31_hasb_4", 14, 0.0, 0.5)]
    fixture = make_fixture("hz31_hasb_4", 14, cells)
    analysis = {
        "page": {"width_points": 200.0, "height_points": 100.0, "page_number": 14, "rotation": 0},
        "groups": [make_group("g001", 20.0, 80.0, "Hohes-C Vitamin Water", "1.29")],
    }
    truth = {"c1": make_truth("c1", "hz31_hasb_4", 14, "Hohes C Vitamin Water", "1.19")}
    row = MODULE.map_fixture(fixture, analysis, truth)[0]
    assert row["title_exact_match"] is False
    assert row["title_normalized_match"] is True
    assert row["normal_price_match"] is False
    assert row["truth_comparison_state"] == "reproducible_disagreement"


def test_multiple_group_centers_fail_closed_to_review():
    cells = [make_cell("c1", "hz31_hasb_4", 14, 0.0, 1.0)]
    fixture = make_fixture("hz31_hasb_4", 14, cells)
    analysis = {
        "page": {"width_points": 200.0, "height_points": 100.0, "page_number": 14, "rotation": 0},
        "groups": [
            make_group("g001", 20.0, 60.0, "A", "1.00"),
            make_group("g002", 120.0, 180.0, "B", "2.00"),
        ],
    }
    truth = {"c1": make_truth("c1", "hz31_hasb_4", 14, "A", "1.00")}
    row = MODULE.map_fixture(fixture, analysis, truth)[0]
    assert row["geometry_binding_state"] == "multiple_center_groups_review_required"
    assert row["geometry_group_id"] is None
    assert row["truth_comparison_state"] == "not_compared"


def test_no_group_center_fails_closed_even_when_group_only_intersects():
    cells = [make_cell("c1", "hz31_hasb_4", 14, 0.0, 0.25)]
    fixture = make_fixture("hz31_hasb_4", 14, cells)
    analysis = {
        "page": {"width_points": 200.0, "height_points": 100.0, "page_number": 14, "rotation": 0},
        "groups": [make_group("g001", 40.0, 120.0, "A", "1.00")],
    }
    truth = {"c1": make_truth("c1", "hz31_hasb_4", 14, "A", "1.00")}
    row = MODULE.map_fixture(fixture, analysis, truth)[0]
    assert row["geometry_binding_state"] == "no_center_group_review_required"
    assert row["center_group_ids"] == []
    assert row["intersecting_group_ids"] == ["g001"]


def test_same_geometry_group_cannot_bind_two_overlapping_n9_cells():
    cells = [
        make_cell("c1", "hz31_hasb_4", 14, 0.0, 0.7),
        make_cell("c2", "hz31_hasb_4", 14, 0.3, 1.0),
    ]
    fixture = make_fixture("hz31_hasb_4", 14, cells)
    analysis = {
        "page": {"width_points": 200.0, "height_points": 100.0, "page_number": 14, "rotation": 0},
        "groups": [make_group("g001", 80.0, 120.0, "A", "1.00")],
    }
    truth = {
        "c1": make_truth("c1", "hz31_hasb_4", 14, "A", "1.00"),
        "c2": make_truth("c2", "hz31_hasb_4", 14, "A", "1.00"),
    }
    rows = MODULE.map_fixture(fixture, analysis, truth)
    assert {row["geometry_binding_state"] for row in rows} == {"cross_cell_group_reuse_review_required"}
    assert all(row["geometry_group_id"] is None for row in rows)
    assert all(row["promotion_ready"] is False for row in rows)


def test_excluded_scope_control_is_never_compared_or_promoted():
    cells = [make_cell("x", "hz31_hasb_4", 14, 0.0, 1.0, excluded=True)]
    fixture = make_fixture("hz31_hasb_4", 14, cells)
    analysis = {
        "page": {"width_points": 200.0, "height_points": 100.0, "page_number": 14, "rotation": 0},
        "groups": [make_group("g001", 20.0, 80.0, "Nonfood", "9.99")],
    }
    truth = {"x": make_truth("x", "hz31_hasb_4", 14, "Nonfood", "9.99")}
    row = MODULE.map_fixture(fixture, analysis, truth)[0]
    assert row["geometry_binding_state"] == "excluded_scope_control"
    assert row["geometry_group_id"] is None
    assert row["truth_comparison_state"] == "not_compared"


def test_n9_contract_requires_17_pages_100_cells_and_six_zero_controls():
    fixtures = []
    active = [
        ("hz31_hasb_4", 14, 7),
        ("hz31_hasb_4", 18, 9),
        ("hz31_hasb_4", 43, 10),
        ("hz32_hasb", 1, 10),
        ("hz32_hasb", 37, 10),
        ("hz32_hasb", 38, 10),
        ("hz32_hasb", 40, 10),
        ("hz32_hasb", 41, 10),
        ("hz32_hasb", 42, 10),
        ("hz32_hasb", 43, 10),
        ("hz32_hasb", 44, 4),
    ]
    serial = 0
    for campaign, page, count in active:
        cells = []
        for index in range(count):
            x0 = index / count
            x1 = (index + 1) / count
            cells.append(make_cell(f"c{serial:03d}", campaign, page, x0, x1))
            serial += 1
        fixtures.append(make_fixture(campaign, page, cells))
    for campaign, page in [
        ("hz31_hasb_4", 10), ("hz31_hasb_4", 12), ("hz31_hasb_4", 20),
        ("hz32_hasb", 10), ("hz32_hasb", 12), ("hz32_hasb", 20),
    ]:
        fixtures.append(make_fixture(campaign, page, []))
    assert serial == 100
    validated = MODULE.validate_n9_manifest(fixtures)
    assert len(validated) == 17


def test_repository_n10_and_geometry_parser_identities_are_exact():
    n10 = MODULE.load_exact_n10(MODULE.DEFAULT_N10)
    assert len(n10) == 100
    parser = MODULE.load_geometry_module()
    assert parser.PARSER_IDENTITY == MODULE.EXPECTED_GEOMETRY_PARSER
