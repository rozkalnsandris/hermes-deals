"""Netto Review overlay is receipt-pinned and never a Hermes offer."""
from datetime import date
from hashlib import sha256
import json

import pytest

from app import netto_booklet_review_layer as layer

DAY = date(2026, 11, 12)
LAST = date(2026, 11, 14)


def capture(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    evidence = root / "netto-html"
    review_root = evidence / "review-layers"
    review_root.mkdir(parents=True)
    publication = {
        "sizes": {"at1600": {"width": 600, "height": 900}},
        "spreads": [{"pages": ["/p/1"]}],
    }
    pub_raw = json.dumps(publication).encode()
    pub_sha = sha256(pub_raw).hexdigest()
    pub_path = evidence / "publication.json"
    pub_path.write_bytes(pub_raw)
    payload = {
        "format": "hermes.netto.pdf_review_projection.v1",
        "state": "REVIEW_ONLY",
        "store_id": "5659", "group": "regionale-hz", "slug": "publication",
        "pdf_sha256": "1" * 64, "publication_sha256": pub_sha,
        "image_manifest_sha256": "2" * 64,
        "alignment_review_sha256": "3" * 64,
        "review_markers_sha256": "4" * 64,
        "page_count": 1, "candidate_count": 1,
        "automatic_offer_links": 0, "verified_product_identities": 0,
        "pages": [{
            "publication_page_number": 1, "publication_page_identifier": "/p/1",
            "pdf_page_number": 1, "candidates": [{
                "candidate_id": "p1-g1",
                "rectangle": {"left": .1, "top": .2, "width": .3, "height": .1},
                "candidate_text_unverified": "<unsafe>",
                "printed_normal_price_candidates_unverified": ["1.99"],
                "review_reasons": ["review_required"],
                "state": "REVIEW_ONLY", "source": "pdf_review_only",
                "hermes_offer_link": None, "verified_product_identity": None,
            }],
        }],
    }
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    digest = sha256(raw).hexdigest()
    (review_root / f"publication-{digest[:12]}.json").write_bytes(raw)
    trust = {
        "store": "5659", "group": "regionale-hz", "snapshot_id": "snapshot",
        "manifest_sha256": "manifest", "publication_sha256": pub_sha,
        "pdf_sha256": "1" * 64, "image_manifest_sha256": "2" * 64,
        "alignment_review_sha256": "3" * 64, "review_markers_sha256": "4" * 64,
        "projection_sha256": digest, "page_count": 1, "candidate_count": 1,
    }
    monkeypatch.setattr(layer, "_TRUSTED_REVIEW_LAYERS", {"publication": trust})
    record = {"slug": "publication", "publication_path": str(pub_path),
              "publication_sha256": pub_sha}
    def call(**changes):
        args = dict(root=root, store_id="5659", snapshot_id="snapshot",
                    manifest_sha256="manifest", record=record, day=DAY,
                    valid_from=DAY, valid_until=LAST)
        args.update(changes)
        return layer.review_only_hotspots(**args)
    return call, review_root, trust


def test_hz46_default_trust_is_disabled_until_exact_projection_hash():
    trust = layer._TRUSTED_REVIEW_LAYERS["hz46_hasb_4"]
    assert trust["pdf_sha256"] == "9d6337beb029977cf8c119cbe2d216b4aab5052523c5e49e6bad0b102418f8cf"
    assert trust["image_manifest_sha256"] == "a23db82f42f2fc2ccc81802aab65b8454979d29c64967077eada59523e87764c"
    assert trust["alignment_review_sha256"] == "0b7fe988e655597480235d927b20e9b14fa920525655e27400a5f4a333c28b93"
    assert trust["candidate_count"] == 686
    assert trust["review_markers_sha256"] is None
    assert trust["projection_sha256"] is None


def test_verified_review_projection_exposes_only_review_marker(tmp_path, monkeypatch):
    call, _, _ = capture(tmp_path, monkeypatch)
    result = call()
    row = result[1][0]
    assert row["rectangle"] == {"left": .1, "top": .2, "width": .3, "height": .1}
    assert row["title"] == "<unsafe>"
    assert row["printed_prices"] == ["1.99"]
    assert row["source"] == "pdf_review_only"
    assert not any(key in row for key in ("offer_id", "href", "sku", "price"))


@pytest.mark.parametrize("change", [
    {"store_id": "9999"}, {"snapshot_id": "other"},
    {"manifest_sha256": "other"}, {"day": date(2026, 11, 15)},
])
def test_wrong_identity_or_date_disables_layer(tmp_path, monkeypatch, change):
    call, _, _ = capture(tmp_path, monkeypatch)
    assert call(**change) == {}


def test_corrupt_or_promotable_projection_fails_closed(tmp_path, monkeypatch):
    call, review_root, trust = capture(tmp_path, monkeypatch)
    path = next(review_root.iterdir())
    payload = json.loads(path.read_text())
    payload["pages"][0]["candidates"][0]["hermes_offer_link"] = "/fake"
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.unlink()
    path = review_root / f"publication-{sha256(raw).hexdigest()[:12]}.json"
    path.write_bytes(raw)
    trust["projection_sha256"] = sha256(raw).hexdigest()
    assert call() == {}


def test_template_escapes_review_text_and_exposes_no_offer_link():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    root = Path(__file__).resolve().parents[2] / "backend/app/north_star/templates"
    env = Environment(loader=FileSystemLoader(root), autoescape=select_autoescape(["html"]))
    rendered = env.get_template("booklets.html").render(
        booklet={
            "state": "ready", "swipeable": True, "retailer_id": "netto",
            "retailer_name": "Netto", "store_name": "5659", "valid_label": "12–14",
            "source_url": "https://wochenprospekt.netto-online.de/hz46_hasb_4/?storeid=5659",
            "image_url": "https://view.publitas.com/p/1-at1600.jpg",
            "page": 1, "page_count": 1, "previous_href": None, "next_href": None,
            "offers": [], "pages": [{
                "number": 1, "href": "/ui/home/?view=booklets",
                "image_url": "https://view.publitas.com/p/1-at1600.jpg",
                "publisher_hotspots": [],
                "review_hotspots": [{
                    "title": "<b>Unsafe</b>", "printed_prices": ["1.99"],
                    "rectangle": {"left": .1, "top": .2, "width": .3, "height": .1},
                }],
            }],
        },
        booklet_retailers=[("netto", "Netto")], selected_date="2026-11-12",
        base_path="/ui/home", view="booklets", csrf_token="synthetic",
    )
    assert "data-booklet-review-hit" in rendered
    assert "&lt;b&gt;Unsafe&lt;/b&gt;" in rendered
    assert 'data-publisher-title="<b>' not in rendered
    assert "PDF · REVIEW KANDIDĀTS" in rendered
    assert "Iespējamā drukātā cena: 1.99" in rendered
    assert "href=\"/fake\"" not in rendered
