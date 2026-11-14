"""Source-only guard for unpublished HZ47 manual visual geometry (#1181)."""
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "evidence/netto/hz47_manual_pdf_geometry_draft_v1.json"
PDF_SHA = "c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a"
SHA = re.compile(r"[0-9a-f]{64}\Z")


def get_draft():
    return json.loads(DRAFT.read_text(encoding="utf-8"))


def test_hz47_draft_explicitly_cannot_publish_or_link_offers():
    draft = get_draft()
    assert draft["format"] == "hermes.netto.hz47_pdf_manual_geometry_draft.v1"
    assert draft["state"] == "REVIEW_ONLY"
    assert draft["pdf_sha256"] == PDF_SHA
    assert draft["source_kind"] == "user_supplied_pdf_not_proven_publisher_bytes"
    assert draft["coordinate_space"] == "pdf_page_normalized_top_left"
    assert SHA.fullmatch(draft["rendered_pages_manifest_sha256"])
    assert draft["publication_ready"] is False
    for key in ("publication_identity_proven", "publisher_page_alignment_proven",
                "store_5659_binding_proven"):
        assert draft[key] is False
    for key in ("automatic_offer_links", "verified_product_identities",
                "product_boundaries_proven"):
        assert draft[key] == 0
    assert draft["screening"] == "visual_contact_sheets_preliminary_not_per_card_verified"


def test_all_72_pages_are_complete_and_preliminary_not_promoted():
    draft = get_draft()
    pages = draft["pages"]
    assert len(pages) == draft["page_count"] == 72
    assert [p["pdf_page_number"] for p in pages] == list(range(1, 73))
    assert sum(bool(p["candidates"]) for p in pages) == draft["page_count_draft_candidates"] == 49
    seen = set()
    total = 0
    for page in pages:
        assert SHA.fullmatch(page["rendered_jpeg_sha256"])
        assert (page["render_width_px"], page["render_height_px"]) == (1352, 1893)
        assert page["full_resolution_pixel_review_completed"] is False
        state = page["layout_screening"]
        assert state in ("candidate_proposal", "excluded_pending_scope_confirmation")
        if state == "excluded_pending_scope_confirmation":
            assert page["candidates"] == []
            assert page["exclusion_note"]
        else:
            assert page["candidates"] and page["exclusion_note"] is None
        for entry in page["candidates"]:
            total += 1
            assert entry["candidate_id"] not in seen
            seen.add(entry["candidate_id"])
            assert entry["candidate_id"].startswith(f"hz47-p{page['pdf_page_number']:02d}-c")
            assert entry["review_state"] == "DRAFT_NEEDS_FULL_RESOLUTION_PIXEL_REVIEW"
            assert entry["product_boundary_proven"] is False
            assert entry["hermes_offer_link"] is None
            assert entry["verified_product_identity"] is None
            assert entry["printed_price_verified"] is None
            assert 2 <= len(entry["source_label_unverified"]) <= 150
            rect = entry["rectangle"]
            assert set(rect) == {"left", "top", "width", "height"}
            assert all(type(v) in (int, float) for v in rect.values())
            assert 0 <= rect["left"] < 1 and 0 <= rect["top"] < 1
            assert 0 < rect["width"] <= 1 and 0 < rect["height"] <= 1
            assert rect["left"] + rect["width"] <= 1
            assert rect["top"] + rect["height"] <= 1
    assert total == draft["candidate_count_draft"] == 262


@pytest.mark.parametrize("page_no", [22,23,39,40,41,44,45,66,67,68,69,70,71])
def test_out_of_scope_or_online_only_pages_are_not_proposed(page_no):
    page = get_draft()["pages"][page_no-1]
    assert not page["candidates"]
    assert page["layout_screening"] == "excluded_pending_scope_confirmation"


def test_draft_has_no_runtime_offer_or_sku_fields():
    raw = DRAFT.read_text(encoding="utf-8")
    for field in ('"offer_id"', '"product_id"', '"sku"', '"href"',
                  '"price_history"', '"price_cents"', '"publication_page_identifier"'):
        assert field not in raw
    assert DRAFT.stat().st_size < 300_000
    assert SHA.fullmatch(sha256(DRAFT.read_bytes()).hexdigest())
