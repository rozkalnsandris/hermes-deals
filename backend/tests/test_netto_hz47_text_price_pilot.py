"""Synthetic source-level tests; no real PDF, offer identities or production writes."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_hz47_text_price_pilot import (
    PDF_SHA256, SCHEMA, accept_links, analyze_words, normalized_rect, preview_html,
)


def fixture():
    # Same block/line split cents and unambiguous printed title; coordinates are synthetic.
    words = [
        (10, 10, 40, 26, "Hackfleisch", 0, 0, 0),
        (42, 10, 80, 26, "gemischt", 0, 0, 1),
        (120, 12, 132, 30, "3.", 1, 0, 0),
        (133, 12, 152, 30, "49*", 1, 0, 1),
        (260, 10, 284, 26, "UVP", 2, 0, 0),
        (288, 10, 310, 26, "4.49", 2, 0, 1),
    ]
    draft = [{"candidate_id": "hz47-p01-c01", "source_label_unverified": "Hackfleisch gemischt",
              "hermes_offer_link": None, "verified_product_identity": None,
              "product_boundary_proven": False}]
    row = analyze_words(words, 1, 400, 400, draft)
    return row


def manifest(row=None):
    return {"schema": SCHEMA, "pdf_sha256": PDF_SHA256,
            "pages": [row or fixture()], "source_local_reviewed_pairs": 0,
            "automatic_offer_links": 0, "verified_product_identities": 0,
            "state": "REVIEW_ONLY", "publication_ready": False}


def review(price="p01-price-001", label="p01-label-c01"):
    return {"schema": "hermes.netto.hz47.source_local_link_review.v1",
            "pdf_sha256": PDF_SHA256,
            "pairs": [{"pdf_page_number": 1, "candidate_id": "hz47-p01-c01",
                       "label_anchor_id": label, "price_anchor_id": price,
                       "reviewed_against_source": True,
                       "rationale": "Printed price ownership checked independently."}]}


def test_native_title_and_split_price_are_unlinked_and_review_only():
    row = fixture()
    assert len(row["anchors"]) == 3
    prices = [a for a in row["anchors"] if a["kind"] == "price"]
    assert prices[0]["literal_text"] == "3. 49*"
    assert "SPLIT_FORMAT" in prices[0]["flags"]
    assert "UVP" in prices[1]["flags"]
    assert all(not a["interactive"] for a in row["anchors"])
    assert row["native_words_sha256"] and row["native_word_count"] == 6


def test_source_local_pair_shares_candidate_id_without_offer_promotion():
    source = manifest()
    accept_links(source, review())
    pair = [a for a in source["pages"][0]["anchors"] if a["interactive"]]
    assert len(pair) == 2
    assert {a["kind"] for a in pair} == {"label", "price"}
    assert {a["candidate_id"] for a in pair} == {"hz47-p01-c01"}
    assert source["automatic_offer_links"] == 0
    assert source["verified_product_identities"] == 0
    assert source["source_local_reviewed_pairs"] == 1
    assert source["publication_ready"] is False


def test_uvp_cannot_link_and_failed_review_does_not_promote():
    source = manifest()
    with pytest.raises(ValueError, match="Ambiguous"):
        accept_links(source, review("p01-price-002"))
    assert not any(a["interactive"] for a in source["pages"][0]["anchors"])
    for changed in ({"pdf_sha256": "0"*64}, {"schema": "bad"}):
        broken = review()
        broken.update(changed)
        with pytest.raises(ValueError, match="provenance"):
            accept_links(manifest(), broken)


def test_collision_duplicate_label_ambiguity_and_invalid_geometries():
    row = fixture()
    assert row["unresolved_labels"] == []
    duplicate = [(10, 10, 40, 26, "Hackfleisch", 0, 0, 0),
                 (42, 10, 80, 26, "gemischt", 0, 0, 1),
                 (10, 100, 40, 126, "Hackfleisch", 1, 0, 0),
                 (42, 100, 80, 126, "gemischt", 1, 0, 1)]
    bad = analyze_words(duplicate, 1, 300, 400, [{"candidate_id": "hz47-p01-c01",
        "source_label_unverified": "Hackfleisch gemischt", "hermes_offer_link": None,
        "verified_product_identity": None, "product_boundary_proven": False}])
    assert bad["unresolved_labels"][0]["native_matches"] == 2
    for rect in ((0, 0, 0, 1), (0, 0, 302, 30), (0, 0, float("nan"), 3),
                 (0, 0, True, 10), (-1, 0, 2, 10)):
        with pytest.raises(ValueError):
            normalized_rect(rect, 300, 400)
    with pytest.raises(ValueError, match="outside exact pilot"):
        analyze_words([], 2, 300, 400)


def test_offline_preview_is_escaped_and_only_approved_anchors_clickable():
    source = manifest()
    row = source["pages"][0]
    assert "<button class=\"anchor\"" not in preview_html(row, "page01.png")
    accept_links(source, review())
    html = preview_html(row, "page01.png")
    assert html.count('<button class="anchor"') == 2
    assert "Unverified PDF source candidate" in html
    assert "pinch" not in html
    assert "<script>" in html
    # User/PDF text never emitted as unsafe HTML.
    row["anchors"][0]["literal_text"] = '<script>alert("x")</script>'
    html = preview_html(row, "page01.png")
    assert '&lt;script&gt;' in html
    assert '<script>alert(' not in html


def test_duplicate_manual_links_fail_closed():
    source = manifest()
    duplicate = review()
    duplicate["pairs"].append(deepcopy(duplicate["pairs"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        accept_links(source, duplicate)
