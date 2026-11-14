"""Fail-closed HZ47 temporal-screening guards. No activation authority."""
import hashlib
import json
from pathlib import Path
from datetime import date
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = ROOT / "evidence/netto/hz47_manual_pdf_geometry_draft_v1.json"
TEMPORAL = ROOT / "evidence/netto/hz47_offline_temporal_context_v1.json"
EXPECTED_GEOMETRY_BLOB = "d11174e3f4f98a1072954fc64ed29f1db84815e8"
PDF_SHA = "c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a"
EXPECTED_HEAD = "c0e61edd2ee417ad98c9f742582536febcb2381a"


def load():
    source = GEOMETRY.read_bytes()
    git_blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
    assert git_blob == EXPECTED_GEOMETRY_BLOB, "STOP: unreviewed geometry drift"
    return json.loads(source), json.loads(TEMPORAL.read_text(encoding="utf-8"))


def test_temporal_receipt_is_offline_and_source_pinned():
    geometry, context = load()
    assert geometry["pdf_sha256"] == context["summary"]["pdf_sha256"] == PDF_SHA
    assert context["schema"] == "hermes.netto.hz47.offline_temporal_screening.v1"
    assert context["status"] == "READ_ONLY_DIAGNOSTIC_NOT_PRODUCTION_TRUST"
    assert context["summary"]["source_commit_checked"] == EXPECTED_HEAD
    assert context["summary"]["source_data_blob"] == EXPECTED_GEOMETRY_BLOB
    assert context["summary"]["deployment_allowed"] is False
    assert geometry["state"] == "REVIEW_ONLY"
    assert geometry["publication_ready"] is False
    assert geometry["automatic_offer_links"] == 0
    assert geometry["product_boundaries_proven"] == 0
    assert context["summary"]["verified_candidate_specific_validity"] == 0
    assert context["summary"]["verified_product_prices"] == 0
    assert context["summary"]["verified_product_identities"] == 0


def test_all_261_candidates_match_page_heading_evidence_without_promotion():
    geometry, context = load()
    assert len(geometry["pages"]) == len(context["pages"]) == 72
    assert len(context["candidates"]) == geometry["candidate_count_draft"] == 261
    expected = {c["candidate_id"]: (p["pdf_page_number"], c, p)
                for p in geometry["pages"] for c in p["candidates"]}
    assert len(expected) == 261
    received = set()
    for printed, source in zip(context["pages"], geometry["pages"]):
        assert printed["page"] == source["pdf_page_number"]
        assert printed["candidates"] == len(source["candidates"])
        assert printed["page_image_sha256"] == source["rendered_jpeg_sha256"]
        assert source["full_resolution_pixel_review_completed"] is False

    contexts = {p["page"]: p for p in context["pages"]}
    for c in context["candidates"]:
        key = c["candidate_id"]
        assert key in expected and key not in received
        received.add(key)
        page, original, _ = expected[key]
        assert c["page"] == page
        assert c["source_label_unverified"] == original["source_label_unverified"]
        assert c["page_heading_category"] == contexts[page]["page_category"]
        assert c["must_not_claim_active_offer"] is True
        assert original["printed_price_verified"] is None
        assert original["verified_product_identity"] is None
        assert original["hermes_offer_link"] is None
        assert original["product_boundary_proven"] is False
        provisional = contexts[page]["printed_candidate_window_not_verified"]
        assert c["printed_page_start_provisional"] == provisional["from"]
        assert c["printed_page_end_provisional"] == provisional["through"]
        start, end = provisional["from"], provisional["through"]
        if start is not None:
            assert end is not None and date.fromisoformat(start) <= date.fromisoformat(end)
        else:
            assert end is None

    assert received == set(expected)


def test_special_calendar_conditions_do_not_imply_active_offers():
    _, ctx = load()
    pages = {p["page"]: p for p in ctx["pages"]}
    expected = {
        6: ("single_day_potential", "2026-11-17", "2026-11-17"),
        7: ("single_day_potential", "2026-11-18", "2026-11-18"),
        **{p: ("printed_range", "2026-11-19", "2026-11-21") for p in range(48, 54)},
        60: ("printed_range", "2026-11-20", "2026-11-21"),
        62: ("printed_range", "2026-11-20", "2026-11-21"),
        32: ("november_catalog", "2026-11-01", "2026-11-30"),
        65: ("checkout_area_condition", None, None),
    }
    for page, (category, start, end) in expected.items():
        record = pages[page]
        assert record["page_category"] == category
        assert record["printed_candidate_window_not_verified"] == {
            "from": start, "through": end
        }
    assert all(c["must_not_claim_active_offer"] for c in ctx["candidates"])


def test_permanent_catalog_is_not_weekly_promotion():
    _, ctx = load()
    for row in ctx["candidates"]:
        if row["page_heading_category"] in ("permanent_catalog", "checkout_area_condition"):
            assert row["printed_page_start_provisional"] is None
            assert row["printed_page_end_provisional"] is None
    hist = Counter(c["page_heading_category"] for c in ctx["candidates"])
    assert hist == {
        "printed_range": 199,
        "single_day_potential": 2,
        "permanent_catalog": 56,
        "november_catalog": 3,
        "checkout_area_condition": 1,
    }


def test_no_individual_price_sku_or_promotion_can_be_inferred():
    geometry, ctx = load()
    assert all(c["review_state"] == "DRAFT_NEEDS_FULL_RESOLUTION_PIXEL_REVIEW"
               for p in geometry["pages"] for c in p["candidates"])
    for c in ctx["candidates"]:
        assert not any(field in c for field in
                       ("verified_valid_from", "verified_valid_to", "price_cents",
                        "sku", "offer_id", "product_id", "is_active", "href"))
    assert ctx["rules"].startswith("page headings are not individual offer validity")
