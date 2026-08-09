from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_full_page_parent_unit_audit import (  # noqa: E402
    CANDIDATE_STRATEGY,
    PAGE_COUNT,
    RECT_MIN_HEIGHT_FRACTION,
    RECT_MIN_WIDTH_FRACTION,
    _sha_payload,
    evaluate_frozen_candidates,
    freeze_parent_candidates,
)


def source_page(page_number: int, *, rectangles: list[dict] | None = None) -> dict:
    return {
        "page_number": page_number,
        "layout_sha256": "a" * 64,
        "images": [],
        "layout": {
            "schema_version": 1,
            "page": {
                "page_number": page_number,
                "width_points": 100.0,
                "height_points": 100.0,
                "rotation": 0,
            },
            "spans": [],
            "vectors": {
                "horizontal_lines": [],
                "vertical_lines": [],
                "rectangles": rectangles or [],
                "filled_rectangles": [],
            },
        },
    }


def prediction_page(page_number: int, *, groups: list[dict] | None = None, spans: list[dict] | None = None) -> dict:
    return {
        "page_number": page_number,
        "analysis": {
            "schema_version": 1,
            "parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
            "page": {
                "page_number": page_number,
                "width_points": 100.0,
                "height_points": 100.0,
                "source_rotation": 0,
            },
            "spans": spans or [],
            "separators": [],
            "filled_rectangles": [],
            "price_anchors": [],
            "groups": groups or [],
        },
    }


def source_payload(rectangles: list[dict]) -> dict:
    pages = [source_page(1, rectangles=rectangles)]
    pages.extend(source_page(index) for index in range(2, PAGE_COUNT + 1))
    return {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "strategy": "netto_heldout_all_pages_source_evidence_v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": "hz33_hasb",
        "campaign_window": {"start": "2026-08-10", "end": "2026-08-15"},
        "source_identity_sha256": "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb",
        "source_manifest_sha256": "b" * 64,
        "source_html_sha256": "c" * 64,
        "source_pdf_sha256": "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba",
        "source_parser_identity": "netto-store-prospect-v1",
        "prediction_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "pymupdf_version": "1.28.0",
        "page_count": PAGE_COUNT,
        "capture_scope": "all_pdf_pages",
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "pages": pages,
    }


def prediction_payload(groups: list[dict], spans: list[dict]) -> dict:
    pages = [prediction_page(1, groups=groups, spans=spans)]
    pages.extend(prediction_page(index) for index in range(2, PAGE_COUNT + 1))
    return {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "strategy": "netto_heldout_all_pages_predictions_v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": "hz33_hasb",
        "campaign_window": {"start": "2026-08-10", "end": "2026-08-15"},
        "source_identity_sha256": "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb",
        "source_pdf_sha256": "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba",
        "prediction_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "page_count": PAGE_COUNT,
        "capture_scope": "all_pdf_pages",
        "truth_included": False,
        "expected_metadata_included": False,
        "review_labels_included": False,
        "review_only": True,
        "promotion_ready": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "pages": pages,
    }


def rectangle(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def group(group_id: str, span_indexes: list[int]) -> dict:
    return {
        "group_id": group_id,
        "title_span_indexes": span_indexes,
        "ambiguous_span_indexes": [],
        "anchor_ids": [],
        "bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0},
        "route": "review_required",
        "production_eligible": False,
    }


def span(index: int, x0: float, y0: float, x1: float, y1: float) -> dict:
    return {
        "index": index,
        "text": f"S{index}",
        "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
        "size": 10.0,
        "font": "Test",
        "color": 0,
        "flags": 0,
    }


def truth_payload(page1_regions: list[dict]) -> dict:
    pages = [
        {
            "page_number": 1,
            "page_width_points": 100.0,
            "page_height_points": 100.0,
            "source_regions": page1_regions,
        }
    ]
    for page_number in range(2, PAGE_COUNT + 1):
        pages.append(
            {
                "page_number": page_number,
                "page_width_points": 100.0,
                "page_height_points": 100.0,
                "source_regions": [],
            }
        )
    return {"pages": pages}


def truth_region(region_id: str, rect: list[float], scope: str = "in_scope") -> dict:
    return {
        "source_region_id": region_id,
        "rect_points": rect,
        "scope_classification": scope,
    }


def test_candidate_reuses_existing_rectangle_separator_thresholds() -> None:
    assert RECT_MIN_WIDTH_FRACTION == 0.10
    assert RECT_MIN_HEIGHT_FRACTION == 0.06
    source = source_payload(
        [
            rectangle(0, 0, 9, 50),  # width 9% -> excluded
            rectangle(0, 0, 20, 20),
        ]
    )
    predictions = prediction_payload([group("g001", [0])], [span(0, 5, 5, 7, 7)])
    frozen = freeze_parent_candidates(source, predictions)
    assert frozen["candidate_strategy"] == CANDIDATE_STRATEGY
    assert len(frozen["pages"][0]["parent_units"]) == 1
    assert frozen["pages"][0]["groups"][0]["candidate_parent_count"] == 1


def test_candidate_preserves_multiple_nested_parents_and_chooses_smallest_primary() -> None:
    source = source_payload(
        [
            rectangle(0, 0, 40, 40),
            rectangle(0, 0, 20, 20),
            rectangle(0, 0, 20, 20),  # deterministic geometry dedup
        ]
    )
    predictions = prediction_payload([group("g001", [0])], [span(0, 5, 5, 7, 7)])
    frozen = freeze_parent_candidates(source, predictions)
    row = frozen["pages"][0]["groups"][0]
    assert row["candidate_parent_count"] == 2
    assert row["candidate_parent_unit_ids"] == ["p001-vr001", "p001-vr002"]
    assert row["primary_parent_unit_id"] == "p001-vr001"
    assert frozen["truth_used_for_candidate_construction"] is False


def test_candidate_freeze_hash_is_independent_of_truth() -> None:
    source = source_payload([rectangle(0, 0, 20, 20)])
    predictions = prediction_payload([group("g001", [0])], [span(0, 5, 5, 7, 7)])
    first = freeze_parent_candidates(source, predictions)
    second = freeze_parent_candidates(deepcopy(source), deepcopy(predictions))
    assert first == second
    clone = {key: value for key, value in first.items() if key != "candidate_freeze_sha256"}
    assert first["candidate_freeze_sha256"] == _sha_payload(clone)
    assert "completed_source_truth_sha256" not in first
    assert "safe_single_source" not in str(first)


def test_truth_evaluation_rejects_vector_container_when_group_crosses_source_regions() -> None:
    source = source_payload([rectangle(0, 0, 40, 40)])
    predictions = prediction_payload(
        [group("g001", [0, 1])],
        [span(0, 5, 5, 7, 7), span(1, 25, 5, 27, 7)],
    )
    frozen = freeze_parent_candidates(source, predictions)
    truth = truth_payload(
        [
            truth_region("p001-r001", [0, 0, 20, 20]),
            truth_region("p001-r002", [20, 0, 40, 20]),
        ]
    )
    evaluation = evaluate_frozen_candidates(frozen, predictions, truth)
    assert evaluation["assigned_parent_count"] == 1
    assert evaluation["parent_truth_counts"] == {"unsafe_cross_source": 1}
    assert evaluation["safe_single_parent_precision"] == 0.0
    assert evaluation["suitable_for_next_heldout_auto_single"] is False
    assert evaluation["decision"] == "candidate_rejected"
    assert evaluation["promotion_ready"] is False


def test_parent_unit_audit_source_has_no_product_or_campaign_override_logic() -> None:
    source = (TOOLS / "netto_full_page_parent_unit_audit.py").read_text(encoding="utf-8")
    for forbidden in (
        "product override",
        "campaign override",
        "expected_title",
        "expected_primary_price_eur",
        "hz31_hasb_4",
        "hz32_hasb",
    ):
        assert forbidden not in source
