from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_local_span_auto_single_candidate import (  # noqa: E402
    GRAPH_GAP_MULTIPLIER,
    MAX_COMPONENT_AREA_FRACTION,
    MIN_OWNED_NODE_FRACTION,
    STRATEGY,
    candidate_rows,
    freeze_candidate,
    payload_sha256,
)


def layout(page_number: int, spans: list[dict], *, vertical_lines: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "page": {"page_number": page_number, "width_points": 100.0, "height_points": 100.0, "rotation": 0},
        "spans": spans,
        "vectors": {
            "horizontal_lines": [],
            "vertical_lines": vertical_lines or [],
            "rectangles": [],
            "filled_rectangles": [],
        },
    }


def span(index: int, x0: float, y0: float, x1: float, y1: float) -> dict:
    return {
        "index": index,
        "text": f"S{index}",
        "bbox": [x0, y0, x1, y1],
        "size": 10.0,
        "font": "Test",
        "color": 0,
        "flags": 0,
    }


def group(group_id: str, indexes: list[int]) -> dict:
    return {
        "group_id": group_id,
        "title_span_indexes": indexes,
        "ambiguous_span_indexes": [],
        "anchor_ids": [],
        "route": "review_required",
        "production_eligible": False,
    }


def source_payload(spans: list[dict], *, vertical_lines: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "strategy": "netto_heldout_all_pages_source_evidence_v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": "future_campaign",
        "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
        "source_identity_sha256": "a" * 64,
        "source_pdf_sha256": "b" * 64,
        "prediction_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "page_count": 1,
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
        "review_only": True,
        "promotion_ready": False,
        "pages": [{"page_number": 1, "layout": layout(1, spans, vertical_lines=vertical_lines)}],
    }


def prediction_payload(spans: list[dict], groups: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "strategy": "netto_heldout_all_pages_predictions_v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": "future_campaign",
        "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
        "source_identity_sha256": "a" * 64,
        "source_pdf_sha256": "b" * 64,
        "prediction_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "page_count": 1,
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
        "review_only": True,
        "promotion_ready": False,
        "pages": [
            {
                "page_number": 1,
                "analysis": {
                    "parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
                    "page": {"page_number": 1, "width_points": 100.0, "height_points": 100.0},
                    "spans": spans,
                    "price_anchors": [],
                    "groups": groups,
                },
            }
        ],
    }


def freeze(spans: list[dict], groups: list[dict], *, vertical_lines: list[dict] | None = None) -> dict:
    return freeze_candidate(
        source_payload(spans, vertical_lines=vertical_lines),
        prediction_payload(spans, groups),
        source_evidence_sha256="c" * 64,
        predictions_sha256="d" * 64,
    )


def test_candidate_config_is_predeclared_and_truth_free() -> None:
    assert GRAPH_GAP_MULTIPLIER == 0.5
    assert MIN_OWNED_NODE_FRACTION == 2.0 / 3.0
    assert MAX_COMPONENT_AREA_FRACTION == 0.005
    payload = freeze([span(0, 1, 1, 3, 3)], [group("g001", [0])])
    assert payload["strategy"] == STRATEGY
    assert payload["truth_used_for_candidate_construction"] is False
    assert payload["automatic_candidate_decisions_frozen"] is True
    assert "truth" not in payload["config"]
    clone = {key: value for key, value in payload.items() if key != "candidate_provenance_sha256"}
    assert payload["candidate_provenance_sha256"] == payload_sha256(clone)


def test_compact_owned_single_group_component_becomes_auto_single_candidate() -> None:
    spans = [span(0, 1, 1, 2, 2), span(1, 2.2, 1, 3.2, 2), span(2, 1, 2.2, 2, 3.2)]
    payload = freeze(spans, [group("g001", [0, 1])])
    rows = candidate_rows(payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_auto_single"] is True
    assert row["parent_unit_count"] == 1
    assert row["parent_group_count"] == 1
    assert row["owned_node_fraction"] >= MIN_OWNED_NODE_FRACTION
    assert row["parent_area_fraction"] <= MAX_COMPONENT_AREA_FRACTION


def test_component_shared_by_two_groups_is_not_candidate() -> None:
    spans = [span(0, 1, 1, 2, 2), span(1, 2.1, 1, 3.1, 2)]
    payload = freeze(spans, [group("g001", [0]), group("g002", [1])])
    assert candidate_rows(payload) == []
    reasons = {row["group_id"]: row["candidate_reasons"] for row in payload["pages"][0]["groups"]}
    assert all("parent_unit_referenced_by_multiple_groups" in value for value in reasons.values())


def test_separator_blocks_nearby_nodes_and_preserves_multi_parent_ambiguity() -> None:
    spans = [span(0, 45, 10, 49, 12), span(1, 51, 10, 55, 12)]
    line = {"x1": 50.0, "y1": 0.0, "x2": 50.0, "y2": 100.0, "length": 100.0}
    payload = freeze(spans, [group("g001", [0, 1])], vertical_lines=[line])
    row = payload["pages"][0]["groups"][0]
    assert row["parent_unit_count"] == 2
    assert row["candidate_auto_single"] is False
    assert "owned_atoms_span_multiple_parent_units" in row["candidate_reasons"]
    assert payload["cross_parent_group_reuse_count"] == 1


def test_candidate_hash_does_not_depend_on_external_truth_object() -> None:
    spans = [span(0, 1, 1, 2, 2)]
    first = freeze(spans, [group("g001", [0])])
    second = freeze(deepcopy(spans), [group("g001", [0])])
    assert first == second
    assert "completed_source_truth_sha256" not in first


def test_candidate_source_has_no_product_campaign_or_truth_specific_rules() -> None:
    source = (TOOLS / "netto_local_span_auto_single_candidate.py").read_text(encoding="utf-8")
    for forbidden in (
        "hz33_hasb",
        "hz34",
        "expected_title",
        "expected_primary_price_eur",
        "product override",
        "campaign override",
        "completed_source_truth",
    ):
        assert forbidden not in source
