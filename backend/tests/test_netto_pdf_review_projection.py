"""Netto PDF Review projection keeps exact page mapping without offer identity."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_pdf_review_projection import ReviewProjectionError, build_projection


PDF = "1" * 64
PUB = "2" * 64
IMG = "3" * 64
MARKERS = "4" * 64
ALIGN = "5" * 64


def fixture():
    markers = {
        "format": "hermes.netto.pdf_review_markers.v1",
        "pdf_sha256": PDF,
        "page_count": 2,
        "publication_page_alignment": "NOT_VERIFIED",
        "retailer_store_identity": "NOT_VERIFIED",
        "offer_identity": "NOT_VERIFIED",
        "automatic_offer_links": 0,
        "candidate_count": 1,
        "pages": [
            {"pdf_page_number": 1, "candidates": [{
                "candidate_id": "g001",
                "marker_bbox": [0.1, 0.2, 0.3, 0.1],
                "marker_basis": "observed_pdf_price_group_only",
                "candidate_text_unverified": "<unsafe>",
                "printed_normal_price_candidates_unverified": ["1.99"],
                "review_reasons": ["review_required"],
                "state": "REVIEW_ONLY",
                "hermes_offer_link": None,
                "verified_product_identity": None,
            }]},
            {"pdf_page_number": 2, "candidates": []},
        ],
    }
    pairs = [
        {"publitas_ordinal": 1, "best_pdf_page": 1, "same_ordinal": True, "reverse_best": True},
        {"publitas_ordinal": 2, "best_pdf_page": 2, "same_ordinal": True, "reverse_best": True},
    ]
    alignment = {
        "schema": "netto-hz46-pdf-publitas-alignment-review-v1",
        "status": "REVIEW_ONLY",
        "inputs": {
            "pdf_sha256": PDF, "publication_sha256": PUB,
            "image_manifest_sha256": IMG, "publication_page_count": 2,
        },
        "result": {
            "same_ordinal_best_matches": 2, "reverse_best_matches": 2,
            "row_best_same_ordinal_80_of_80": True,
            "column_best_same_ordinal_80_of_80": True,
            "row_best_is_bijection": True, "mismatch_count": 0,
        },
        "pairs": pairs,
    }
    images = {
        "schema": "netto-hz46-publitas-image-retention-review-v1",
        "pdf_sha256": PDF, "publication_sha256": PUB, "page_count": 2,
        "pages": [
            {"ordinal": 1, "page_path": "/p/one"},
            {"ordinal": 2, "page_path": "/p/two"},
        ],
    }
    return markers, alignment, images


def project():
    return build_projection(
        *fixture(), store_id="5659", group="regionale-hz", slug="hz46_hasb_4",
        review_markers_sha256=MARKERS, alignment_review_sha256=ALIGN,
        image_manifest_sha256=IMG,
    )


def test_exact_alignment_projects_review_geometry_only():
    result = project()
    assert result["candidate_count"] == 1
    row = result["pages"][0]["candidates"][0]
    assert row["candidate_id"] == "p001-g001"
    assert row["source_candidate_id"] == "g001"
    assert row["rectangle"] == {"left": .1, "top": .2, "width": .3, "height": .1}
    assert row["candidate_text_unverified"] == "<unsafe>"
    assert row["printed_normal_price_candidates_unverified"] == ["1.99"]
    assert row["state"] == "REVIEW_ONLY"
    assert row["source"] == "pdf_review_only"
    assert row["hermes_offer_link"] is None
    assert row["verified_product_identity"] is None


def test_same_page_local_group_id_on_different_pages_gets_stable_scoped_ids():
    markers, alignment, images = fixture()
    duplicate = dict(markers["pages"][0]["candidates"][0])
    markers["pages"][1]["candidates"] = [duplicate]
    markers["candidate_count"] = 2
    result = build_projection(
        markers, alignment, images, store_id="5659", group="regionale-hz",
        slug="hz46_hasb_4", review_markers_sha256=MARKERS,
        alignment_review_sha256=ALIGN, image_manifest_sha256=IMG,
    )
    rows = [page["candidates"][0] for page in result["pages"]]
    assert [row["candidate_id"] for row in rows] == ["p001-g001", "p002-g001"]
    assert [row["source_candidate_id"] for row in rows] == ["g001", "g001"]


def test_duplicate_page_local_group_id_on_same_page_fails_closed():
    markers, alignment, images = fixture()
    markers["pages"][0]["candidates"].append(
        dict(markers["pages"][0]["candidates"][0])
    )
    markers["candidate_count"] = 2
    with pytest.raises(ReviewProjectionError, match="page-local candidate identity"):
        build_projection(
            markers, alignment, images, store_id="5659", group="regionale-hz",
            slug="hz46_hasb_4", review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN, image_manifest_sha256=IMG,
        )


@pytest.mark.parametrize("field,value", [
    ("same_ordinal_best_matches", 1),
    ("reverse_best_matches", 1),
    ("row_best_is_bijection", False),
    ("mismatch_count", 1),
])
def test_nonexact_alignment_fails_closed(field, value):
    markers, alignment, images = fixture()
    alignment["result"][field] = value
    with pytest.raises(ReviewProjectionError):
        build_projection(
            markers, alignment, images, store_id="5659", group="regionale-hz",
            slug="hz46_hasb_4", review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN, image_manifest_sha256=IMG,
        )


def test_forged_geometry_or_offer_identity_fails_closed():
    markers, alignment, images = fixture()
    markers["pages"][0]["candidates"][0]["marker_bbox"] = [0.9, 0.2, 0.2, 0.1]
    with pytest.raises(ReviewProjectionError):
        build_projection(
            markers, alignment, images, store_id="5659", group="regionale-hz",
            slug="hz46_hasb_4", review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN, image_manifest_sha256=IMG,
        )
    markers, alignment, images = fixture()
    markers["pages"][0]["candidates"][0]["hermes_offer_link"] = "/fake"
    with pytest.raises(ReviewProjectionError):
        build_projection(
            markers, alignment, images, store_id="5659", group="regionale-hz",
            slug="hz46_hasb_4", review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN, image_manifest_sha256=IMG,
        )


def test_swapped_page_identity_fails_closed():
    markers, alignment, images = fixture()
    alignment["pairs"][1]["best_pdf_page"] = 1
    with pytest.raises(ReviewProjectionError):
        build_projection(
            markers, alignment, images, store_id="5659", group="regionale-hz",
            slug="hz46_hasb_4", review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN, image_manifest_sha256=IMG,
        )



def product_card_fixture():
    markers, alignment, images = fixture()
    markers["format"] = "hermes.netto.pdf_product_card_review_markers.v2"
    markers["verified_product_identities"] = 0
    markers["product_boundaries_proven"] = 0
    row = markers["pages"][0]["candidates"][0]
    row.update({
        "candidate_id": "c001",
        "source_candidate_id": "native-card-1",
        "source_price_region_id": "native-word-7",
        "source_product_image_region_id": "native-image-3",
        "marker_basis": "observed_pdf_product_card_candidate",
        "product_boundary_proven": False,
    })
    row["marker_bbox"] = [0.08, 0.12, 0.42, 0.31]
    row["candidate_text_unverified"] = "Hähnchen-Brustfilet mager 1 kg"
    return markers, alignment, images


def test_product_card_v2_projects_whole_card_geometry_and_provenance_only():
    result = build_projection(
        *product_card_fixture(),
        store_id="5659",
        group="regionale-hz",
        slug="hz46_hasb_4",
        review_markers_sha256=MARKERS,
        alignment_review_sha256=ALIGN,
        image_manifest_sha256=IMG,
    )

    assert result["format"] == "hermes.netto.pdf_product_card_review_projection.v2"
    assert result["product_boundaries_proven"] == 0
    assert result["automatic_offer_links"] == 0
    assert result["verified_product_identities"] == 0
    row = result["pages"][0]["candidates"][0]
    assert row["candidate_id"] == "p001-c001"
    assert row["source_candidate_id"] == "c001"
    assert row["native_source_candidate_id"] == "native-card-1"
    assert row["source_price_region_id"] == "native-word-7"
    assert row["source_product_image_region_id"] == "native-image-3"
    assert row["rectangle"] == {
        "left": .08,
        "top": .12,
        "width": .42,
        "height": .31,
    }
    assert row["source"] == "pdf_product_card_review_only"
    assert row["product_boundary_proven"] is False
    assert row["hermes_offer_link"] is None
    assert row["verified_product_identity"] is None


@pytest.mark.parametrize("field,value", [
    ("product_boundary_proven", True),
    ("hermes_offer_link", "/fake"),
    ("verified_product_identity", "fake"),
])
def test_product_card_v2_cannot_promote_identity_or_boundary(field, value):
    markers, alignment, images = product_card_fixture()
    markers["pages"][0]["candidates"][0][field] = value
    with pytest.raises(ReviewProjectionError):
        build_projection(
            markers,
            alignment,
            images,
            store_id="5659",
            group="regionale-hz",
            slug="hz46_hasb_4",
            review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN,
            image_manifest_sha256=IMG,
        )


def test_product_card_v2_requires_native_source_provenance():
    markers, alignment, images = product_card_fixture()
    markers["pages"][0]["candidates"][0]["source_product_image_region_id"] = ""
    with pytest.raises(ReviewProjectionError, match="source provenance"):
        build_projection(
            markers,
            alignment,
            images,
            store_id="5659",
            group="regionale-hz",
            slug="hz46_hasb_4",
            review_markers_sha256=MARKERS,
            alignment_review_sha256=ALIGN,
            image_manifest_sha256=IMG,
        )
