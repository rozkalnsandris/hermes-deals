"""Tests for Review-only Netto PDF product-card marker export v2."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_pdf_product_card_review_export import (
    MARKER_BASIS,
    ProductCardReviewExportError,
    review_page,
)


def native_fixture():
    return {
        "product_card_candidates": [{
            "candidate_id": "native-card-1",
            "price_region_id": "native-word-12",
            "price_text": "7.99*",
            "price_bbox": [0.858, 0.500, 0.082, 0.051],
            "product_text": "Hähnchen-Brustfilet mager",
            "product_text_region_ids": ["native-word-7", "native-word-8"],
            "product_image_region_id": "native-image-1",
            "product_image_bbox": [0.522, 0.298, 0.444, 0.231],
            "card_bbox": [0.510, 0.286, 0.468, 0.294],
            "basis": "native_pdf_product_text_image_price_card_v2",
            "review_reasons": [
                "product_boundary_review_only",
                "product_identity_unverified",
            ],
            "product_boundary_proven": False,
            "verified_product_identity": None,
            "hermes_offer_link": None,
            "state": "REVIEW_ONLY",
        }]
    }


def test_review_page_exports_product_card_not_price_rectangle():
    result = review_page(native_fixture(), 1)
    assert result["pdf_page_number"] == 1
    assert len(result["candidates"]) == 1
    row = result["candidates"][0]
    assert row["candidate_id"] == "c001"
    assert row["source_candidate_id"] == "native-card-1"
    assert row["source_price_region_id"] == "native-word-12"
    assert row["source_product_image_region_id"] == "native-image-1"
    assert row["marker_bbox"] == [0.51, 0.286, 0.468, 0.294]
    assert row["marker_basis"] == MARKER_BASIS
    assert row["candidate_text_unverified"] == "Hähnchen-Brustfilet mager"
    assert row["printed_normal_price_candidates_unverified"] == ["7.99"]
    assert row["product_boundary_proven"] is False
    assert row["verified_product_identity"] is None
    assert row["hermes_offer_link"] is None
    assert row["state"] == "REVIEW_ONLY"


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "VERIFIED"),
        ("product_boundary_proven", True),
        ("verified_product_identity", "fake-product"),
        ("hermes_offer_link", "/fake-offer"),
    ],
)
def test_review_page_rejects_promoted_or_linked_candidate(field, value):
    native = native_fixture()
    native["product_card_candidates"][0][field] = value
    with pytest.raises(ProductCardReviewExportError, match="fail-closed"):
        review_page(native, 1)


def test_review_page_rejects_out_of_page_card_geometry():
    native = native_fixture()
    native["product_card_candidates"][0]["card_bbox"] = [0.8, 0.2, 0.3, 0.4]
    with pytest.raises(ProductCardReviewExportError, match="outside page"):
        review_page(native, 1)


def test_review_page_rejects_missing_product_text_or_image_identity():
    native = native_fixture()
    native["product_card_candidates"][0]["product_text"] = ""
    with pytest.raises(ProductCardReviewExportError, match="metadata"):
        review_page(native, 1)

    native = native_fixture()
    native["product_card_candidates"][0]["product_image_region_id"] = ""
    with pytest.raises(ProductCardReviewExportError, match="metadata"):
        review_page(native, 1)
