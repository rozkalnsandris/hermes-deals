"""Synthetic source-registered Lidl physical-store original-booklet checks."""
import base64
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import pytest

from app import lidl_verified_booklets as v

DAY = date(2026, 11, 2)
NOW = datetime(2026, 11, 3, tzinfo=timezone.utc)
FLYER = "01a17709-8249-7615-b563-dc7ab8c43523"
SLUG = "aktionsprospekt-02-11-2026-07-11-2026-test12"
VIEWER = f"https://www.lidl.de/l/prospekte/{SLUG}/ar/7"
API_URL = (
    "https://endpoints.leaflets.schwarz/v4/flyer?"
    f"version=4&flyer_identifier={SLUG}&client=lidl&region_id=7"
)


def src_url(number, quality, flyer=FLYER):
    source = f"s3://leaflets/images/{flyer}/page-{number:02d}_{'a'*32}.png"
    token = base64.urlsafe_b64encode(source.encode()).decode().rstrip("=")
    size = "1200" if quality == "normal" else "2400"
    return (
        "https://imgproxy.leaflets.schwarz/"
        + "X"*43 + f"/rs:fit:{size}:{size}:1/g:no/{token}.jpg"
    )


def corpus(tmp_path, *, region="7", viewer=VIEWER):
    root = tmp_path / "lidl-booklets"
    root.mkdir()
    hub = f'<html><a href="{viewer}">Aktionsprospekt 02.11.2026 - 07.11.2026</a></html>'.encode()
    api = {
        "success": True, "version": 4,
        "flyer": {
            "id": FLYER, "regions": [{"code": region}],
            "offerStartDate": "2026-11-02", "offerEndDate": "2026-11-07",
            "flyerUrlAbsolute": viewer,
            "pages": [],
        },
    }
    pages = []
    for number in range(1, 4):
        row = {"number": number}
        page = {"number": number, "type": "STANDARD"}
        for quality, field in (("normal", "image"), ("large", "zoom")):
            folder = root / "pages" / quality
            folder.mkdir(parents=True, exist_ok=True)
            data = b"\xff\xd8\xff" + (f"lidl{number}:{quality}".encode()*80) + b"\xff\xd9"
            (folder / f"bk_{number:02d}.jpg").write_bytes(data)
            url = src_url(number, quality)
            row[quality] = {
                "path": f"pages/{quality}/bk_{number:02d}.jpg",
                "source_url": url, "sha256": sha256(data).hexdigest(),
                "bytes": len(data),
            }
            page[field] = url
        api["flyer"]["pages"].append(page)
        pages.append(row)
    api_bytes = json.dumps(api, sort_keys=True).encode()
    (root / "hub.html").write_bytes(hub)
    (root / "api.json").write_bytes(api_bytes)
    meta = {
        "schema": v.SCHEMA, "retailer": "lidl",
        "store_external_id": "DE06664", "store_entity_id": "6664",
        "scope": "physical_store_family_original", "region": "7",
        "source_page": v.HUB, "api_url": API_URL,
        "viewer_url": viewer, "source_flyer_id": FLYER,
        "hub_html_sha256": sha256(hub).hexdigest(),
        "api_json_sha256": sha256(api_bytes).hexdigest(),
        "valid_from": "2026-11-02", "valid_until": "2026-11-07",
        "state": "candidate_only_unregistered", "publication_authorized": False,
        "pdf_retained": False, "page_count": 3, "pages": pages,
        "observed_at": "2026-11-01T13:00:00+00:00",
        "expires_at": "2026-12-01T13:00:00+00:00",
    }
    return root,meta


def register(root, meta):
    raw = (json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (root / "capture.json").write_bytes(raw)
    return sha256(raw).hexdigest()


def read(root, digest, **kw):
    return v.read_verified_lidl_booklet(DAY, root=root, manifest_sha256=digest,
                                        now=NOW, **kw)


def test_unregistered_cannot_display_or_serve(monkeypatch,tmp_path):
    monkeypatch.delenv("LIDL_FAMILY_BOOKLET_CAPTURE_SHA256", raising=False)
    assert v.read_verified_lidl_booklet(DAY, root=tmp_path) is None
    with pytest.raises(ValueError):
        v.read_verified_lidl_image(1, "normal", root=tmp_path)


def test_full_corpus_normal_zoom_navigation_and_http_route(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    root,meta=corpus(tmp_path)
    digest=register(root,meta)
    out=read(root,digest)
    assert out["state"]=="ready" and out["page_count"]==3 and out["offers"]==[]
    assert out["image_url"]=="/ui/home/booklet-assets/lidl/normal/1"
    assert out["pages"][-1]["zoom_image_url"]=="/ui/home/booklet-assets/lidl/large/3"
    assert "retailer=lidl" in out["next_href"] and out["previous_href"] is None
    assert read(root,digest,page=3)["next_href"] is None
    assert read(root,digest,page=4)["state"]=="missing_page"
    assert v.read_verified_lidl_image(3, "large", root=root, manifest_sha256=digest, now=NOW)==(root/"pages/large/bk_03.jpg").read_bytes()
    monkeypatch.setattr(v,"_root",lambda requested: root if requested is None else requested)
    monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED","1")
    monkeypatch.delenv("LIDL_FAMILY_BOOKLET_CAPTURE_SHA256",raising=False)
    with TestClient(app) as client:
        path="/ui/home/booklet-assets/lidl/large/3"
        assert client.get(path).status_code==404
        monkeypatch.setenv("LIDL_FAMILY_BOOKLET_CAPTURE_SHA256",digest)
        response=client.get(path)
        assert response.status_code==200
        assert response.content==(root/"pages/large/bk_03.jpg").read_bytes()
        assert response.headers["cache-control"]=="private, no-store"
        assert response.headers["x-content-type-options"]=="nosniff"
        assert client.get("/ui/home/booklet-assets/lidl/large/4").status_code==404
        monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED","0")
        assert client.get(path).status_code==404


@pytest.mark.parametrize("field,bad",[
    ("store_external_id","DE99999"),("store_entity_id","6665"),
    ("region","0"),("viewer_url","https://evil.example/ar/7"),
    ("scope","online_only"),("source_flyer_id","fake"),
    ("valid_until","2026-11-08"),("page_count",75),
    ("publication_authorized",True),("pdf_retained",True),
    ("expires_at","2027-01-01T13:00:00+00:00")
])
def test_manifest_wrong_family_and_expiry_fails_closed(tmp_path,field,bad):
    root,meta=corpus(tmp_path)
    meta[field]=bad
    assert read(root,register(root,meta))["state"]=="unavailable"


def test_generic_region_zero_api_must_not_activate_family(tmp_path):
    root,meta=corpus(tmp_path,region="0")
    assert read(root,register(root,meta))["state"]=="unavailable"


def test_no_ar7_hub_link_must_not_activate_family(tmp_path):
    root,meta=corpus(tmp_path)
    (root/"hub.html").write_bytes(b'<a href="/l/prospekte/generic/ar/0">generic</a>')
    meta["hub_html_sha256"]=sha256((root/"hub.html").read_bytes()).hexdigest()
    assert read(root,register(root,meta))["state"]=="unavailable"


def test_source_tampering_or_symlink_fail_closed(tmp_path):
    root,meta=corpus(tmp_path)
    sha=register(root,meta)
    (root/"api.json").write_bytes(b'{}')
    assert read(root,sha)["state"]=="unavailable"
    (root/"api.json").write_bytes(json.dumps({"unexpected":"source"}).encode())
    assert read(root,sha)["state"]=="unavailable"
    (root/"pages/large/bk_03.jpg").write_bytes(b"\xff\xd8\xff" + b"corrupt"*80 + b"\xff\xd9")
    assert read(root,sha)["state"]=="unavailable"
    alias=tmp_path/"alias"
    alias.symlink_to(root,target_is_directory=True)
    assert read(alias,sha)["state"]=="unavailable"


def test_invalid_source_url_page_quality_and_date(tmp_path):
    root,meta=corpus(tmp_path)
    meta["pages"][0]["large"]["source_url"]=src_url(1,"normal")
    assert read(root,register(root,meta))["state"]=="unavailable"
    meta["pages"][0]["large"]["source_url"]=src_url(1,"large")
    assert v.read_verified_lidl_booklet(date(2026,11,8),root=root,manifest_sha256=register(root,meta),now=NOW) is None
    assert not v._image_source(src_url(1,"normal"),2,"normal",FLYER)
    assert not v._image_source(src_url(1,"normal"),1,"large",FLYER)


def test_expired_retention_blocks_both_pages_and_images(tmp_path):
    root,meta=corpus(tmp_path)
    digest=register(root,meta)
    assert v.read_verified_lidl_booklet(DAY,root=root,manifest_sha256=digest,now=NOW+timedelta(days=38))["state"]=="unavailable"
    with pytest.raises(ValueError):
        v.read_verified_lidl_image(1,"normal",root=root,manifest_sha256=digest,now=NOW+timedelta(days=38))
