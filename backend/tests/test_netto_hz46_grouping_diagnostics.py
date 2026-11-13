from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_hz46_grouping_diagnostics.py"
FIXTURE = (
    ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "netto"
    / "hz46_pages3_5_offer_golden_v1.json"
)
SPEC = importlib.util.spec_from_file_location(
    "netto_hz46_grouping_diagnostics",
    TOOL,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _native_row(
    region_id: str,
    text: str,
    bbox: list[float],
    block_no: int,
    *,
    line_no: int = 0,
    word_no: int = 0,
) -> dict:
    return {
        "region_id": region_id,
        "text": text,
        "bbox": bbox,
        "block_no": block_no,
        "line_no": line_no,
        "word_no": word_no,
        "state": "REVIEW_ONLY",
    }


def _image(region_id: str, bbox: list[float]) -> dict:
    return {
        "region_id": region_id,
        "bbox": bbox,
        "pixel_width": 320,
        "pixel_height": 240,
        "xref": 21,
        "digest": "aa",
        "state": "REVIEW_ONLY",
    }


def test_hz46_golden_fixture_tracks_23_slots_without_inventing_unresolved_truth():
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert golden["strategy"] == MODULE.GOLDEN_STRATEGY
    assert golden["publication"]["slug"] == "hz46_hasb_4"
    assert golden["publication"]["store_id"] == "5659"
    assert golden["safety"] == {
        "review_only": True,
        "automatic_offer_links": 0,
        "verified_product_identities": 0,
        "product_boundaries_proven": 0,
        "automatic_publish_enabled": False,
    }

    pages = {page["page_number"]: page for page in golden["pages"]}
    assert {page: row["expected_offer_count"] for page, row in pages.items()} == {
        3: 8,
        4: 7,
        5: 8,
    }
    offers = [offer for page in pages.values() for offer in page["offers"]]
    assert len(offers) == 23

    unresolved = [offer for offer in offers if offer["expected_title"] is None]
    assert [offer["golden_id"] for offer in unresolved] == ["p04-02"]
    assert unresolved[0]["required_title_tokens"] == []
    assert unresolved[0]["expected_primary_price"] is None

    kiwi = next(offer for offer in offers if offer["golden_id"] == "p03-01")
    assert kiwi["expected_title"] == "Kiwi grün"
    assert kiwi["expected_primary_price"] is None

    tafelspitz = next(offer for offer in offers if offer["golden_id"] == "p05-01")
    assert tafelspitz["expected_primary_price"] == "1.49"
    assert tafelspitz["price_basis"] == "100 g"


def test_diagnostics_preserve_text_and_image_alternatives_when_card_is_not_emitted():
    native = {
        "text_regions": [
            _native_row("title", "Mövenpick Feinjoghurt", [0.45, 0.32, 0.15, 0.03], 1),
            _native_row("price", "0.69", [0.52, 0.42, 0.08, 0.05], 2),
        ],
        "image_regions": [
            _image("native-image-21", [0.50, 0.25, 0.16, 0.12]),
        ],
        "primary_price_candidates": [
            {
                "region_id": "price",
                "text": "0.69",
                "bbox": [0.52, 0.42, 0.08, 0.05],
            }
        ],
        "product_card_candidates": [],
        "date_price_region_ids_excluded": [],
    }

    result = MODULE.diagnose_page(native, 4)

    assert result["pdf_page_number"] == 4
    assert result["primary_price_anchor_count"] == 1
    anchor = result["anchors"][0]
    assert anchor["status"] == "rejected_or_ambiguous"
    assert anchor["rejection_reasons"] == [
        "evidence_exists_but_current_card_not_emitted"
    ]
    assert anchor["text_alternatives"][0]["text"] == "Mövenpick Feinjoghurt"
    assert anchor["text_alternatives"][0]["product_text_signal"] is True
    assert anchor["image_alternatives"][0]["region_id"] == "native-image-21"
    assert anchor["image_alternatives"][0]["within_current_gap_limit"] is True
    assert anchor["image_alternatives"][0]["within_current_owner_radius"] is True


def test_diagnostics_distinguish_missing_image_evidence_from_grouping_rejection():
    native = {
        "text_regions": [
            _native_row("title", "Chiquita Bananen", [0.20, 0.20, 0.16, 0.03], 1),
            _native_row("price", "1.99", [0.30, 0.34, 0.08, 0.05], 2),
        ],
        "image_regions": [],
        "primary_price_candidates": [
            {
                "region_id": "price",
                "text": "1.99",
                "bbox": [0.30, 0.34, 0.08, 0.05],
            }
        ],
        "product_card_candidates": [],
        "date_price_region_ids_excluded": [],
    }

    anchor = MODULE.diagnose_page(native, 3)["anchors"][0]

    assert anchor["status"] == "missing_evidence"
    assert anchor["rejection_reasons"] == [
        "no_product_image_alternative_within_current_limits"
    ]
    assert anchor["text_alternatives"]


def test_golden_evaluation_separates_title_match_price_mismatch_and_unresolved_truth():
    native = {
        "product_card_candidates": [
            {
                "candidate_id": "native-card-1",
                "product_text": "Mövenpick Feinjoghurt oder Sahnepudding",
                "price_text": "0.79",
            },
            {
                "candidate_id": "native-card-2",
                "product_text": "Leerdammer Scheiben XXL",
                "price_text": "3,99*",
            },
        ],
        "price_text_candidates": [
            {
                "candidate_id": "native-price-text-1",
                "assignment_state": "SELECTED",
                "product_text": "Mövenpick Feinjoghurt oder Sahnepudding",
                "price_text": "0.69",
            },
            {
                "candidate_id": "native-price-text-2",
                "assignment_state": "SELECTED",
                "product_text": "Leerdammer Scheiben XXL",
                "price_text": "3,99*",
            },
        ],
    }
    golden_page = {
        "page_number": 4,
        "expected_offer_count": 3,
        "offers": [
            {
                "golden_id": "movenpick",
                "expected_title": "Mövenpick Feinjoghurt oder Sahnepudding",
                "required_title_tokens": ["mövenpick", "feinjoghurt"],
                "expected_primary_price": "0.69",
            },
            {
                "golden_id": "leerdammer",
                "expected_title": "Leerdammer Scheiben XXL",
                "required_title_tokens": ["leerdammer", "xxl"],
                "expected_primary_price": "3.99",
            },
            {
                "golden_id": "unresolved",
                "expected_title": None,
                "required_title_tokens": [],
                "expected_primary_price": None,
            },
        ],
    }

    result = MODULE.evaluate_page(native, golden_page)
    outcomes = {row["golden_id"]: row for row in result["outcomes"]}

    assert result["resolved_truth_slots"] == 2
    assert result["matched_title_slots"] == 2
    assert result["matched_title_price_slots"] == 1
    assert result["price_text_candidate_count"] == 2
    assert result["price_text_matched_title_slots"] == 2
    assert result["price_text_matched_title_price_slots"] == 2
    assert result["price_text_ambiguous_slots"] == 0
    assert outcomes["movenpick"]["status"] == "price_mismatch"
    assert outcomes["leerdammer"]["status"] == "matched"
    assert outcomes["unresolved"]["status"] == "truth_unresolved"

    price_text_outcomes = {
        row["golden_id"]: row for row in result["price_text_outcomes"]
    }
    assert price_text_outcomes["movenpick"]["status"] == "matched"
    assert price_text_outcomes["leerdammer"]["status"] == "matched"
    assert price_text_outcomes["unresolved"]["status"] == "truth_unresolved"



def test_golden_evaluation_ignores_unresolved_price_text_assignments():
    native = {
        "product_card_candidates": [],
        "price_text_candidates": [
            {
                "candidate_id": "native-price-text-1",
                "assignment_state": "UNRESOLVED",
                "product_text": "Chiquita Bananen",
                "price_text": "1.99",
            },
        ],
    }
    golden_page = {
        "page_number": 3,
        "expected_offer_count": 1,
        "offers": [
            {
                "golden_id": "bananen",
                "expected_title": "Chiquita Bananen",
                "required_title_tokens": ["chiquita", "bananen"],
                "expected_primary_price": "1.99",
            },
        ],
    }

    result = MODULE.evaluate_page(native, golden_page)

    assert result["price_text_candidate_count"] == 1
    assert result["price_text_matched_title_slots"] == 0
    assert result["price_text_matched_title_price_slots"] == 0
    assert result["price_text_outcomes"][0]["status"] == "missing"

def test_golden_fixture_fails_closed_if_identity_boundary_is_relaxed():
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    golden["safety"]["automatic_offer_links"] = 1

    with pytest.raises(
        MODULE.GroupingDiagnosticsError,
        match="identity boundary",
    ):
        MODULE._validate_golden(golden)
