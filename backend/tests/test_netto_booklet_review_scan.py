"""Offline source-bound Netto booklet Review projection regressions."""
from datetime import date
from hashlib import sha256
import json

import pytest

from app.netto_booklet_review_scan import scan_netto_review_candidates

DAY = date(2026, 11, 2)
END = date(2026, 11, 7)


def publication(*, dimensions=True):
    data = {
        "spreads": [
            {"pages": ["/netto/p1"], "hotspots": [
                {"id": 10, "type": "product",
                 "position": {"left": 0.2, "top": 0.3, "width": 0.2, "height": 0.1},
                 "products": [{"id": 123}]},
                {"id": 99, "type": "externalLink", "url": "javascript:alert(1)"},
            ]},
            {"pages": ["/netto/p2", "/netto/p3"], "hotspots": [
                {"id": 11, "type": "product", "title": "<script>bad()</script>",
                 "position": {"left": 0.4, "top": 0.1, "width": 0.2, "height": 0.5},
                 "products": [{"id": 456}, {"id": 789}]},
            ]},
        ],
    }
    if dimensions:
        data["sizes"] = {"at1600": {"width": 600, "height": 900}}
    return data


def scan(data=None, **kwargs):
    raw = json.dumps(publication() if data is None else data, sort_keys=True).encode()
    args = dict(store_id="5659", day=DAY, valid_from=DAY, valid_until=END)
    args.update(kwargs)
    return scan_netto_review_candidates(raw, sha256(raw).hexdigest(), **args)


def test_single_spread_and_two_page_clipping_have_bounded_page_geometry():
    result = scan()
    assert result["state"] == "review_only"
    assert result["verified_offer_links"] == 0
    assert result["page_count"] == 3
    assert result["source_page_dimensions"] == {"width": 600.0, "height": 900.0, "size": "at1600"}
    candidates = result["candidates"]
    assert [(c["hotspot_id"], c["page_number"]) for c in candidates] == [
        (10, 1), (11, 2), (11, 3),
    ]
    assert candidates[0]["rectangle"] == {"left": .2, "top": .3, "width": .2, "height": .1}
    assert candidates[1]["rectangle"] == {"left": .8, "top": .1, "width": .2, "height": .5}
    assert candidates[2]["rectangle"] == {"left": 0.0, "top": .1, "width": .2, "height": .5}
    assert all(c["status"] == "review_only" and "offer_id" not in c for c in candidates)
    assert candidates[1]["publisher_product_ids"] == [456, 789]
    assert not any("<script>" in str(c) or "javascript:" in str(c) for c in candidates)


def test_missing_or_untrusted_page_dimensions_prevent_projection():
    for size in (None, {"width": 0, "height": 800}, {"width": "600", "height": 800}):
        data = publication(dimensions=False)
        if size is not None:
            data["sizes"] = {"at1600": size}
        result = scan(data)
        assert len(result["candidates"]) == 2
        assert all(c["page_number"] is None and c["rectangle"] is None
                   and c["reason"] == "source_page_dimensions_unverified"
                   for c in result["candidates"])
        assert result["source_page_dimensions"] is None


@pytest.mark.parametrize("replace", [
    {"store_id": "6071"},
    {"day": date(2026, 11, 8)},
    {"valid_from": date(2026, 11, 3)},
    {"valid_until": date(2026, 12, 10)},
    {"day": "2026-11-02"},
])
def test_wrong_store_and_unverified_dates_fail_closed(replace):
    with pytest.raises(ValueError):
        scan(**replace)


def test_sha_and_json_are_verified_before_projection():
    data = publication()
    raw = json.dumps(data).encode()
    with pytest.raises(ValueError, match="SHA"):
        scan_netto_review_candidates(raw, "0" * 64,
                                     store_id="5659", day=DAY, valid_from=DAY, valid_until=END)
    with pytest.raises(ValueError):
        scan_netto_review_candidates(b"<not-json>", sha256(b"<not-json>").hexdigest(),
                                     store_id="5659", day=DAY, valid_from=DAY, valid_until=END)


@pytest.mark.parametrize("key,value", [
    ("left", -0.01), ("top", 1.01), ("width", 0), ("height", -1),
    ("left", 0.9), ("width", 0.9), ("top", float("nan")),
    ("left", "0.4"), ("top", True),
])
def test_forged_or_invalid_geometry_is_rejected(key, value):
    data = publication()
    data["spreads"][0]["hotspots"][0]["position"][key] = value
    with pytest.raises(ValueError):
        scan(data)


@pytest.mark.parametrize("hotspot_id", [0, -5, "123", True])
def test_invalid_hotspot_ids_are_rejected(hotspot_id):
    data = publication()
    data["spreads"][0]["hotspots"][0]["id"] = hotspot_id
    with pytest.raises(ValueError):
        scan(data)


@pytest.mark.parametrize("product_id", [0, -1, "123", True])
def test_invalid_product_ids_are_rejected(product_id):
    data = publication()
    data["spreads"][0]["hotspots"][0]["products"] = [{"id": product_id}]
    with pytest.raises(ValueError):
        scan(data)


def test_ambiguous_duplicate_hotspot_or_product_claims_are_rejected():
    data = publication()
    data["spreads"][1]["hotspots"][0]["id"] = 10
    with pytest.raises(ValueError, match="Duplicated"):
        scan(data)
    data = publication()
    data["spreads"][1]["hotspots"][0]["products"] = [{"id": 456}, {"id": 456}]
    with pytest.raises(ValueError, match="Duplicate product"):
        scan(data)


def test_cross_spread_product_reuse_is_review_only_not_claimed_identity():
    data = publication()
    data["spreads"][1]["hotspots"][0]["products"] = [{"id": 123}]
    rows = scan(data)["candidates"]
    assert len(rows) == 3
    assert all(c["status"] == "review_only" for c in rows)


def test_wrong_page_counts_and_paths_rejected_by_existing_publication_validator():
    data = publication()
    data["spreads"][1]["pages"].append("/netto/p4")
    with pytest.raises(ValueError, match="one or two"):
        scan(data)
    data = publication()
    data["spreads"][1]["pages"][0] = "/netto/p1"
    with pytest.raises(ValueError, match="Duplicate"):
        scan(data)


def test_stable_replay_and_no_automatic_promotion():
    result = scan()
    assert result == scan()
    assert result["verified_offer_links"] == 0
    assert all("href" not in candidate and "canonical_product" not in candidate
               and "price" not in candidate for candidate in result["candidates"])
