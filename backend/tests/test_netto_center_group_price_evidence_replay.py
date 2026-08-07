from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_center_group_price_evidence_replay.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_center_group_price_evidence_replay_tested",
    TOOL,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_cell(
    cell_id: str,
    x0: float,
    x1: float,
    *,
    excluded: bool = False,
) -> dict[str, object]:
    return {
        "cell_id": cell_id,
        "publication_slug": "hz31_hasb_4",
        "page_number": 14,
        "scope_state": "excluded_non_target_card" if excluded else "target_or_review_card",
        "region_x0": x0,
        "region_y0": 0.0,
        "region_x1": x1,
        "region_y1": 1.0,
    }


def make_fixture(cells: list[dict[str, object]]) -> dict[str, object]:
    return {
        "page": {
            "publication_slug": "hz31_hasb_4",
            "page_number": 14,
        },
        "cells": cells,
    }


def make_group(
    group_id: str,
    x0: float,
    x1: float,
    *,
    normal: str | None,
    member: str | None = None,
    normal_candidates: list[str] | None = None,
    member_candidates: list[str] | None = None,
    route: str = "review_required",
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "group_id": group_id,
        "bbox": {"x0": x0, "y0": 20.0, "x1": x1, "y1": 80.0},
        "selected_title": "diagnostic title",
        "selected_normal_price": normal,
        "selected_member_price": member,
        "normal_price_candidates": normal_candidates or ([] if normal is None else [normal]),
        "member_price_candidates": member_candidates or ([] if member is None else [member]),
        "route": route,
        "reasons": reasons or ["title_independent_evidence_required"],
    }


def make_truth(cell_id: str) -> dict[str, object]:
    return {
        "cell_id": cell_id,
        "publication_slug": "hz31_hasb_4",
        "page_number": 14,
        "expected_title": "truth",
        "expected_primary_price_eur": "3.99",
    }


def analysis(groups: list[dict[str, object]]) -> dict[str, object]:
    return {
        "page": {
            "width_points": 200.0,
            "height_points": 100.0,
            "page_number": 14,
            "rotation": 0,
        },
        "groups": groups,
    }


def test_group_price_evidence_is_bounded_and_deterministic() -> None:
    group = make_group(
        "g001",
        20.0,
        80.0,
        normal="3.99",
        member="3.79",
        normal_candidates=["4.49", "3.99"],
        member_candidates=["3.99", "3.79"],
        reasons=["z_reason", "a_reason"],
    )
    evidence = MODULE.group_price_evidence(group)
    assert evidence == {
        "group_id": "g001",
        "selected_normal_price": "3.99",
        "selected_member_price": "3.79",
        "normal_price_candidates": ["3.99", "4.49"],
        "member_price_candidates": ["3.79", "3.99"],
        "route": "review_required",
        "reasons": ["a_reason", "z_reason"],
    }
    assert "selected_title" not in evidence


def test_multiple_centers_keep_base_binding_and_expose_each_price_group() -> None:
    cells = [make_cell("c1", 0.0, 1.0)]
    fixture = make_fixture(cells)
    page_analysis = analysis(
        [
            make_group(
                "g002",
                120.0,
                180.0,
                normal="4.99",
            ),
            make_group(
                "g001",
                20.0,
                60.0,
                normal="3.99",
                member="3.79",
            ),
        ]
    )

    row = MODULE.build_fixture_evidence(fixture, page_analysis)[0]
    base_row = MODULE.BASE.map_fixture(
        fixture,
        page_analysis,
        {"c1": make_truth("c1")},
    )[0]

    assert row["geometry_binding_state"] == base_row["geometry_binding_state"]
    assert row["geometry_binding_state"] == "multiple_center_groups_review_required"
    assert row["geometry_group_id"] is None
    assert row["center_group_ids"] == ["g001", "g002"]
    assert [
        value["group_id"] for value in row["center_group_price_evidence"]
    ] == ["g001", "g002"]
    assert row["center_group_price_evidence"][0]["selected_normal_price"] == "3.99"
    assert row["center_group_price_evidence"][0]["selected_member_price"] == "3.79"
    assert row["review_only"] is True
    assert row["promotion_ready"] is False


def test_single_center_binding_is_unchanged_and_exposes_one_group() -> None:
    cells = [make_cell("c1", 0.0, 0.5)]
    fixture = make_fixture(cells)
    page_analysis = analysis(
        [make_group("g001", 20.0, 60.0, normal="10.49", member="9.99")]
    )

    row = MODULE.build_fixture_evidence(fixture, page_analysis)[0]
    base_row = MODULE.BASE.map_fixture(
        fixture,
        page_analysis,
        {"c1": make_truth("c1")},
    )[0]

    assert row["geometry_binding_state"] == base_row["geometry_binding_state"]
    assert row["geometry_binding_state"] == "single_center_group"
    assert row["geometry_group_id"] == "g001"
    assert row["center_group_price_evidence"] == [
        {
            "group_id": "g001",
            "selected_normal_price": "10.49",
            "selected_member_price": "9.99",
            "normal_price_candidates": ["10.49"],
            "member_price_candidates": ["9.99"],
            "route": "review_required",
            "reasons": ["title_independent_evidence_required"],
        }
    ]


def test_cross_cell_group_reuse_binding_remains_fail_closed() -> None:
    cells = [
        make_cell("c1", 0.0, 0.7),
        make_cell("c2", 0.3, 1.0),
    ]
    fixture = make_fixture(cells)
    page_analysis = analysis(
        [make_group("g001", 80.0, 120.0, normal="2.99", member="2.79")]
    )

    rows = MODULE.build_fixture_evidence(fixture, page_analysis)
    base_rows = MODULE.BASE.map_fixture(
        fixture,
        page_analysis,
        {"c1": make_truth("c1"), "c2": make_truth("c2")},
    )

    assert [row["geometry_binding_state"] for row in rows] == [
        row["geometry_binding_state"] for row in base_rows
    ]
    assert {
        row["geometry_binding_state"] for row in rows
    } == {"cross_cell_group_reuse_review_required"}
    assert all(row["geometry_group_id"] is None for row in rows)
    assert all(len(row["center_group_price_evidence"]) == 1 for row in rows)


def test_excluded_scope_never_exports_center_group_price_evidence() -> None:
    fixture = make_fixture([make_cell("x", 0.0, 1.0, excluded=True)])
    page_analysis = analysis(
        [make_group("g001", 20.0, 80.0, normal="9.99", member="8.99")]
    )
    row = MODULE.build_fixture_evidence(fixture, page_analysis)[0]
    assert row["geometry_binding_state"] == "excluded_scope_control"
    assert row["geometry_group_id"] is None
    assert row["center_group_price_evidence"] == []
    assert row["promotion_ready"] is False


def test_sidecar_source_has_no_n10_or_independent_truth_dependency() -> None:
    source = TOOL.read_text(encoding="utf-8").casefold()
    assert "load_exact_n10" not in source
    assert "default_n10" not in source
    assert "expected_title" not in source
    assert "expected_primary_price" not in source
    assert "independent-review" not in source
    assert "completed-independent" not in source


def test_create_only_writer_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    MODULE.write_create_only(path, {"value": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 1}
    with pytest.raises(MODULE.CenterGroupPriceEvidenceError, match="already exists"):
        MODULE.write_create_only(path, {"value": 2})


def test_replay_summary_remains_review_only() -> None:
    fixtures = []
    serial = 0
    active = [
        ("hz31_hasb_4", 14, 26),
        ("hz32_hasb", 1, 74),
    ]
    for campaign, page_number, count in active:
        cells = []
        for index in range(count):
            cells.append(
                {
                    "cell_id": f"c{serial:03d}",
                    "publication_slug": campaign,
                    "page_number": page_number,
                    "scope_state": "target_or_review_card",
                    "region_x0": index / count,
                    "region_y0": 0.0,
                    "region_x1": (index + 1) / count,
                    "region_y1": 1.0,
                }
            )
            serial += 1
        fixtures.append(
            {
                "page": {
                    "publication_slug": campaign,
                    "page_number": page_number,
                },
                "cells": cells,
            }
        )

    def fake_analyze(_pdf: Path, page_number: int) -> dict[str, object]:
        return {
            "page": {
                "width_points": 200.0,
                "height_points": 100.0,
                "page_number": page_number,
                "rotation": 0,
            },
            "groups": [],
        }

    payload = MODULE.replay_center_group_price_evidence(
        fixtures,
        {
            "hz31_hasb_4": Path("kw31.pdf"),
            "hz32_hasb": Path("kw32.pdf"),
        },
        analyze_page=fake_analyze,
    )
    assert payload["strategy"] == "netto_center_group_price_evidence_replay_v1"
    assert payload["cell_count"] == 100
    assert payload["review_only"] is True
    assert payload["promotion_ready"] is False
    assert payload["automatic_approval_enabled"] is False
    assert payload["automatic_publish_enabled"] is False
    assert payload["database_write_performed"] is False
