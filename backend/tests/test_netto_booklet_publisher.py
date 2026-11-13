"""Publisher-only Netto hotspot capture: no false SKU/offer promotion."""
from datetime import date
from hashlib import sha256
import json

import pytest

from app import netto_booklet_publisher as publisher

DAY = date(2026, 11, 2)
LAST = date(2026, 11, 7)


def test_hz46_trust_binding_is_exact_and_publisher_only():
    trust = publisher._TRUSTED_PUBLICATIONS["hz46_hasb_4"]
    assert trust == {
        "store": "5659",
        "group": "regionale-hz",
        "publication_sha256": "68184db39b6cb9878d6eab2e804ab767310390135e5f12772762329c661ac087",
        "receipt_sha256": "20960935b4ff65a1754e24a642699bd84e03194b72975a2871a6adfaa647cd0c",
        "snapshot_id": "962b80c9-a0bc-4553-8aa8-adf15857573b",
        "manifest_sha256": "c17eb05f4378f77c469175d94448b319895370ee2b51e13871fa4800e636e687",
        "product_count": 13,
    }
    assert set(trust) == {
        "store", "group", "publication_sha256", "receipt_sha256",
        "snapshot_id", "manifest_sha256", "product_count",
    }


def capture(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    evidence = root / "netto-html"
    evidence.mkdir(parents=True, exist_ok=True)
    pub = {"sizes": {"at1600": {"width": 600, "height": 900}},
           "spreads": [{"pages": ["/p/1"], "hotspots": [{
               "id": 11, "type": "product",
               "position": {"left": 0.2, "top": 0.3, "width": 0.2, "height": 0.1},
               "products": [{"id": 21}]
           }]}]}
    raw = json.dumps(pub).encode()
    ps = sha256(raw).hexdigest()
    (evidence / "publication.json").write_bytes(raw)
    detail = json.dumps({"id": 21, "hotspotId": 11,
                         "title": "<b>Publisher's item</b>"}).encode()
    digest = sha256(detail).hexdigest()
    receipt = json.dumps({"snapshot_id": "snapshot", "manifest_sha256": "manifest",
                          "publication_sha256": ps, "slug": "publication", "group": "source",
                          "products": [{"sha256": digest}]}).encode()
    receipt_digest = sha256(receipt).hexdigest()
    location = evidence / ("publitas-product-details-publication-" + ps)
    location.mkdir(exist_ok=True)
    (location / "receipt.json").write_bytes(receipt)
    (location / ("product-21-" + digest[:12] + ".json")).write_bytes(detail)
    monkeypatch.setattr(publisher, "_TRUSTED_PUBLICATIONS", {"publication": {
        "store": "5659", "group": "source", "publication_sha256": ps,
        "receipt_sha256": receipt_digest, "snapshot_id": "snapshot",
        "manifest_sha256": "manifest", "product_count": 1,
    }})
    record = {"slug": "publication", "publication_path": str(evidence / "publication.json"),
              "publication_sha256": ps}
    def call(**changes):
        args = dict(store_id="5659", snapshot_id="snapshot", manifest_sha256="manifest",
                    record=record, day=DAY, valid_from=DAY, valid_until=LAST)
        args.update(changes)
        return publisher.publisher_only_hotspots(root, **args)
    return call, location, record


def test_verified_publisher_detail_exposes_coordinates_without_offer_identity(tmp_path, monkeypatch):
    call, _, _ = capture(tmp_path, monkeypatch)
    result = call()
    assert list(result) == [1]
    h = result[1][0]
    assert h["rectangle"] == {"left": .2, "top": .3, "width": .2, "height": .1}
    assert h["title"] == "<b>Publisher's item</b>"
    assert h["source"] == "publitas_publisher_only"
    assert not any(key in h for key in ("offer_id", "href", "sku", "price"))


@pytest.mark.parametrize("change", [
    {"store_id": "5658"}, {"day": date(2026, 11, 8)},
    {"valid_from": date(2026, 11, 3)},
])
def test_untrusted_store_or_date_disables_overlay(tmp_path, monkeypatch, change):
    call, _, _ = capture(tmp_path, monkeypatch)
    assert call(**change) == {}


def test_same_publication_survives_collector_snapshot_rollover(tmp_path, monkeypatch):
    call, _, _ = capture(tmp_path, monkeypatch)
    result = call(snapshot_id="new-snapshot", manifest_sha256="new-manifest")
    assert sum(len(rows) for rows in result.values()) == 1


def test_changed_publication_identity_disables_overlay(tmp_path, monkeypatch):
    call, _, record = capture(tmp_path, monkeypatch)
    record["publication_sha256"] = "0" * 64
    assert call() == {}


def test_corrupt_receipt_or_product_fails_closed(tmp_path, monkeypatch):
    call, location, _ = capture(tmp_path, monkeypatch)
    (location / "receipt.json").write_text('{"bad":1}')
    assert call() == {}
    call, location, _ = capture(tmp_path, monkeypatch)
    data = next(p for p in location.iterdir() if p.name != "receipt.json")
    data.write_text('{"id":21,"hotspotId":999,"title":"Wrong"}')
    assert call() == {}


def test_mismatched_hotspot_identity_fails_closed(tmp_path, monkeypatch):
    call, location, _ = capture(tmp_path, monkeypatch)
    detail_path = next(p for p in location.iterdir() if p.name != "receipt.json")
    raw = json.loads(detail_path.read_bytes())
    raw["hotspotId"] = 12
    changed = json.dumps(raw).encode()
    digest = sha256(changed).hexdigest()
    detail_path.unlink()
    (location / ("product-21-" + digest[:12] + ".json")).write_bytes(changed)
    receipt_path = location / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["products"][0]["sha256"] = digest
    new_receipt = json.dumps(receipt).encode()
    receipt_path.write_bytes(new_receipt)
    trust = publisher._TRUSTED_PUBLICATIONS["publication"]
    trust["receipt_sha256"] = sha256(new_receipt).hexdigest()
    assert call() == {}


def test_missing_dimensions_cannot_create_clickable_hotspots(tmp_path, monkeypatch):
    call, location, record = capture(tmp_path, monkeypatch)
    pub_path = tmp_path / "raw" / "netto-html" / "publication.json"
    pub = json.loads(pub_path.read_bytes())
    pub.pop("sizes")
    raw = json.dumps(pub).encode()
    pub_path.write_bytes(raw)
    # A changed publication can never inherit the old immutable capture.
    assert call() == {}


def test_template_only_exposes_publisher_button_from_server_verified_page():
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    root = Path(__file__).resolve().parents[2] / "backend/app/north_star/templates"
    env = Environment(loader=FileSystemLoader(root),autoescape=select_autoescape(["html"]))
    rendered = env.get_template("booklets.html").render(
        booklet={"state": "ready", "swipeable": True, "retailer_id": "netto",
                 "retailer_name": "Netto", "store_name": "5659", "valid_label": "02–07",
                 "source_url": "https://wochenprospekt.netto-online.de/hz45_hasb/?storeid=5659",
                 "image_url": "https://view.publitas.com/p/1-at1600.jpg",
                 "page": 1, "page_count": 1, "previous_href": None, "next_href": None,
                 "offers": [], "pages": [{"number": 1, "href": "/ui/home/?view=booklets",
                   "image_url": "https://view.publitas.com/p/1-at1600.jpg",
                   "publisher_hotspots": [{"title": "<b>Unsafe</b>", "description": "",
                       "rectangle": {"left": .2, "top": .3, "width": .2, "height": .1}}]}]},
        booklet_retailers=[("netto", "Netto")], selected_date="2026-11-02",
        base_path="/ui/home", view="booklets", csrf_token="synthetic")
    assert "data-booklet-publisher-hit" in rendered
    assert "&lt;b&gt;Unsafe&lt;/b&gt;" in rendered
    assert 'data-publisher-title="<b>' not in rendered
