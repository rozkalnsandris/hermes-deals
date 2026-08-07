from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/netto_ownership_separator_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_ownership_separator_audit_tested",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

GEOMETRY = MODULE.BASE.load_geometry_module()
TRUTH_PATH = ROOT / "backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"


def fixture(*, excluded: bool = False) -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_id": "cell-1",
                "publication_slug": "hz31_hasb_4",
                "page_number": 1,
                "scope_state": "excluded_non_target_card" if excluded else "target_or_review_card",
                "region_x0": 0.0,
                "region_y0": 0.0,
                "region_x1": 1.0,
                "region_y1": 1.0,
            }
        ]
    }


def layout(*, vertical_separator: bool = False) -> dict[str, object]:
    vertical_lines = []
    if vertical_separator:
        vertical_lines.append(
            {
                "x1": 50.0,
                "y1": 0.0,
                "x2": 50.0,
                "y2": 100.0,
                "length": 100.0,
            }
        )
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
            "vertical_lines": vertical_lines,
            "rectangles": [],
            "filled_rectangles": [],
        },
    }


def group(group_id: str, x0: float, x1: float, *, route: str = "review_required") -> dict[str, object]:
    return {
        "group_id": group_id,
        "bbox": {"x0": x0, "y0": 40.0, "x1": x1, "y1": 60.0},
        "route": route,
        "reasons": ["title_independent_evidence_required"],
        "normal_price_candidates": [],
        "member_price_candidates": [],
        "selected_normal_price": None,
        "selected_member_price": None,
    }


def analysis(groups: list[dict[str, object]]) -> dict[str, object]:
    return {
        "page": {
            "width_points": 100.0,
            "height_points": 100.0,
            "page_number": 1,
            "rotation": 0,
        },
        "groups": groups,
    }


def test_multiple_price_groups_without_source_separator_coalesce_for_ownership_only() -> None:
    rows = MODULE.audit_fixture(
        fixture(),
        layout(),
        analysis([group("g001", 10.0, 30.0), group("g002", 65.0, 85.0)]),
        GEOMETRY,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["current_binding"] == "multiple_center_groups_review_required"
    assert row["candidate_ownership_binding"] == "single_ownership_cluster_coalesced"
    assert row["ownership_group_ids"] == ["g001", "g002"]
    assert row["separator_pair_count"] == 0
    assert row["review_only"] is True
    assert row["promotion_ready"] is False


def test_detected_source_separator_keeps_multiple_groups_fail_closed() -> None:
    rows = MODULE.audit_fixture(
        fixture(),
        layout(vertical_separator=True),
        analysis([group("g001", 10.0, 30.0), group("g002", 65.0, 85.0)]),
        GEOMETRY,
    )
    row = rows[0]
    assert row["current_binding"] == "multiple_center_groups_review_required"
    assert row["candidate_ownership_binding"] == "multiple_ownership_clusters_review_required"
    assert row["ownership_group_ids"] == []
    assert row["separator_pair_count"] == 1
    assert row["pair_evidence"][0]["separator_between"] is True


def test_single_group_remains_single_ownership_cluster() -> None:
    rows = MODULE.audit_fixture(
        fixture(),
        layout(),
        analysis([group("g001", 35.0, 65.0)]),
        GEOMETRY,
    )
    row = rows[0]
    assert row["current_binding"] == "single_center_group"
    assert row["candidate_ownership_binding"] == "single_ownership_cluster"
    assert row["ownership_group_ids"] == ["g001"]


def test_excluded_scope_control_cannot_become_ownership_candidate() -> None:
    rows = MODULE.audit_fixture(
        fixture(excluded=True),
        layout(),
        analysis([group("g001", 35.0, 65.0)]),
        GEOMETRY,
    )
    row = rows[0]
    assert row["current_binding"] == "excluded_scope_control"
    assert row["candidate_ownership_binding"] == "excluded_scope_control"
    assert row["ownership_group_ids"] == []


def test_no_center_group_remains_review_required() -> None:
    rows = MODULE.audit_fixture(
        fixture(),
        layout(),
        analysis([]),
        GEOMETRY,
    )
    row = rows[0]
    assert row["current_binding"] == "no_center_group_review_required"
    assert row["candidate_ownership_binding"] == "no_center_group_review_required"
    assert row["ownership_group_ids"] == []


def test_truth_is_not_an_input_to_source_ownership_classification() -> None:
    signature = inspect.signature(MODULE.audit_fixture)
    assert list(signature.parameters) == [
        "fixture",
        "layout",
        "analysis",
        "geometry_module",
    ]
    classify_signature = inspect.signature(MODULE.classify_center_groups)
    assert "truth" not in classify_signature.parameters
    assert "independent" not in classify_signature.parameters


def test_frozen_independent_ownership_summary_has_exact_contract() -> None:
    payload = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    assert payload["strategy"] == "netto_n2_independent_ownership_summary_v1"
    assert payload["source_completed_independent_ledger_sha256"] == (
        "2fb5c5675d2b05b53da1f37cf4d1f66d32d152f3c7d77c0786d0400b5d30330a"
    )
    assert payload["source_adjudication_sha256"] == (
        "59319ade8a5164b036a4f68474c36d46568c09dd9034e380c6928c15d2331088"
    )
    assert payload["source_n9_fixture_manifest_sha256"] == MODULE.BASE.EXPECTED_N9_MANIFEST_SHA256
    assert payload["cell_count"] == 100
    assert payload["single_source_count"] == 88
    assert payload["mixed_source_count"] == 10
    assert payload["excluded_control_count"] == 2
    assert len(set(payload["mixed_cell_ids"])) == 10
    assert len(set(payload["excluded_control_cell_ids"])) == 2
    assert not set(payload["mixed_cell_ids"]) & set(payload["excluded_control_cell_ids"])
    assert payload["truth_use_contract"] == "adjudication_only_not_parser_or_geometry_selection"


def test_candidate_scoring_reports_confusion_without_affecting_rows() -> None:
    rows = [
        {
            "cell_id": "mixed-hit",
            "candidate_ownership_binding": "multiple_ownership_clusters_review_required",
            "review_only": True,
            "promotion_ready": False,
        },
        {
            "cell_id": "mixed-miss",
            "candidate_ownership_binding": "single_ownership_cluster",
            "review_only": True,
            "promotion_ready": False,
        },
        {
            "cell_id": "single-ok",
            "candidate_ownership_binding": "single_ownership_cluster_coalesced",
            "review_only": True,
            "promotion_ready": False,
        },
        {
            "cell_id": "single-fp",
            "candidate_ownership_binding": "multiple_ownership_clusters_review_required",
            "review_only": True,
            "promotion_ready": False,
        },
        {
            "cell_id": "excluded",
            "candidate_ownership_binding": "excluded_scope_control",
            "review_only": True,
            "promotion_ready": False,
        },
    ]
    truth = {
        "mixed-hit": "mixed_source",
        "mixed-miss": "mixed_source",
        "single-ok": "single_source",
        "single-fp": "single_source",
        "excluded": "excluded_control",
    }
    score = MODULE._score(rows, truth)
    assert score == {
        "tp": 1,
        "fp": 1,
        "tn": 1,
        "fn": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
        "mixed_review_only_count": 2,
    }
