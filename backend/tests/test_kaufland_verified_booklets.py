"""Network-free Kaufland Aplerbeck original-page reader tests."""
import base64
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import pytest
from app import kaufland_verified_booklets as v
from app.kaufland_booklets import build_kaufland_booklet

DAY = date(2026, 11, 2)
CLOCK = datetime(2026, 11, 3, tzinfo=timezone.utc)


def url(number, quality="normal"):
    if number == 69:
        raw = v.PROMOTION_ORIGINAL
        size = "rs:fill:729:1200:1" if quality == "normal" else "rs:fill:1458:2400:1"
    else:
        raw = f"s3://leaflets/images/{v.FLYER_ID}/page-{number:02d}_{'a'*32}.png"
        size = "rs:fit:1200:1200:1" if quality == "normal" else "rs:fit:2400:2400:1"
    encoded = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return f"{v.IMAGE_BASE}{'X'*43}/{size}/g:no/{encoded}.jpg"


def corpus(tmp_path):
    root = tmp_path / "kaufland-booklets"
    root.mkdir()
    pages = []
    for n in range(1, v.COUNT + 1):
        row = {"number": n}
        for q in v.QUALITIES:
            folder = root / "pages" / q
            folder.mkdir(parents=True, exist_ok=True)
            raw = b"\xff\xd8\xff" + (f"{n}:{q}:".encode()*75) + b"\xff\xd9"
            (folder / f"bk_{n:02d}.jpg").write_bytes(raw)
            row[q] = {"path": f"pages/{q}/bk_{n:02d}.jpg",
                      "source_url": url(n, q), "bytes": len(raw),
                      "sha256": sha256(raw).hexdigest()}
        pages.append(row)
    meta = {
        "schema": v.SCHEMA, "retailer": "kaufland", "store_id": "1503",
        "source_flyer_id": v.FLYER_ID, "scope": "family_primary_kaufland",
        "source_page": v.SOURCE, "source_html_sha256": "a"*64,
        "api_json_sha256": "b"*64,
        "viewer_url": v.VIEWER, "valid_from": "2026-11-01", "valid_until": "2026-11-07",
        "state": "candidate_only_unregistered", "publisher_urls_may_rotate": True,
        "pdf_retained": False, "publication_authorized": False,
        "page_count": 69, "pages": pages,
        "observed_at": "2026-11-01T12:00:00+00:00",
        "expires_at": "2026-12-01T12:00:00+00:00",
    }
    return root, meta


def register(root, meta):
    body = (json.dumps(meta, sort_keys=True, separators=(",", ":"))+"\n").encode()
    (root/"capture.json").write_bytes(body)
    return sha256(body).hexdigest()


# First-party viewer source observed 2026-11-01; not synthetic identity.
OFFICIAL_PAGE_1 = (
    "https://imgproxy.leaflets.schwarz/"
    "S7tG5WlnTAEVYFxqy9nvsRLUdGVhlemsxYxGX2vCMgE/"
    "rs:fit:1200:1200:1/g:no/"
    "czM6Ly9sZWFmbGV0cy9pbWFnZXMvMDFhMTgzMWYtMmY5Yy03ZTNkLTk2ZmYtNzJjM2NmNzgzZjgwL3BhZ2UtMDFfYmQ4ZjBiZGI3MzQ2ZDQyMmJkNzQwZmY2MGQ1ZjI3Y2EucG5n.jpg"
)


def test_official_original_image_url_is_bound_to_flyer():
    assert v._valid_image_url(OFFICIAL_PAGE_1, 1)
    assert not v._valid_image_url(OFFICIAL_PAGE_1, 2)


def test_signed_urls_bound_to_exact_issue_page():
    assert v._valid_image_url(url(1), 1)
    assert not v._valid_image_url(url(1), 2)
    assert v._valid_image_url(url(69, "normal"), 69, "normal")
    assert v._valid_image_url(url(69, "large"), 69, "large")
    assert not v._valid_image_url(url(69, "large"), 69, "normal")
    assert not v._valid_image_url(url(1)+"?token=secret", 1)
    assert not v._valid_image_url(url(1).replace("imgproxy.leaflets.schwarz", "bad.example"), 1)


def test_unregistered_preserves_official_store_link(monkeypatch, tmp_path):
    monkeypatch.delenv("KAUFLAND_APLERBECK_CAPTURE_SHA256", raising=False)
    assert v.read_verified_kaufland_booklet(DAY, root=tmp_path) is None
    with pytest.raises(ValueError):
        v.read_verified_kaufland_image(1, "normal", root=tmp_path)
    assert build_kaufland_booklet(DAY, today=DAY)["state"] == "external_link"
    assert build_kaufland_booklet(date(2026, 10, 1), today=DAY)["state"] == "unavailable"


def test_registered_full_pages_navigation(tmp_path):
    root,meta=corpus(tmp_path)
    digest=register(root,meta)
    out=v.read_verified_kaufland_booklet(DAY,root=root,manifest_sha256=digest,now=CLOCK)
    assert out["state"]=="ready" and out["page_count"]==69 and out["offers"]==[]
    assert out["image_url"]=="/ui/home/booklet-assets/kaufland/normal/1"
    assert out["pages"][-1]["zoom_image_url"].endswith("/large/69")
    assert out["previous_href"] is None and "retailer=kaufland" in out["next_href"]
    assert v.read_verified_kaufland_booklet(DAY,page=69,root=root,manifest_sha256=digest,now=CLOCK)["next_href"] is None
    assert v.read_verified_kaufland_booklet(DAY,page=70,root=root,manifest_sha256=digest,now=CLOCK)["state"]=="missing_page"
    assert v.read_verified_kaufland_image(69,"large",root=root,manifest_sha256=digest,now=CLOCK)==(root/"pages/large/bk_69.jpg").read_bytes()


@pytest.mark.parametrize("field,bad",[
    ("store_id","1504"),("source_flyer_id","wrong"),("scope","wrong"),
    ("page_count",68),("valid_until","2026-11-14"),
    ("viewer_url","https://evil.example/"),("state","ready"),
    ("publication_authorized",True),("expires_at","2027-01-01T12:00:00+00:00"),
])
def test_wrong_source_or_expiry_fails_closed(tmp_path,field,bad):
    root,meta=corpus(tmp_path)
    meta[field]=bad
    assert v.read_verified_kaufland_booklet(DAY,root=root,manifest_sha256=register(root,meta),now=CLOCK)["state"]=="unavailable"


def test_page_source_tamper_and_symlink_fail_closed(tmp_path):
    root,meta=corpus(tmp_path)
    meta["pages"][0]["normal"]["source_url"]=url(2)
    assert v.read_verified_kaufland_booklet(DAY,root=root,manifest_sha256=register(root,meta),now=CLOCK)["state"]=="unavailable"
    meta["pages"][0]["normal"]["source_url"]=url(1)
    digest=register(root,meta)
    (root/"pages/large/bk_69.jpg").write_bytes(b"\xff\xd8\xff"+b"tampered"*60+b"\xff\xd9")
    assert v.read_verified_kaufland_booklet(DAY,root=root,manifest_sha256=digest,now=CLOCK)["state"]=="unavailable"
    alias=tmp_path/"alias"
    alias.symlink_to(root,target_is_directory=True)
    assert v.read_verified_kaufland_booklet(DAY,root=alias,manifest_sha256=digest,now=CLOCK)["state"]=="unavailable"


def test_registered_http_endpoint(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    root,meta=corpus(tmp_path)
    digest=register(root,meta)
    monkeypatch.setattr(v,"_root",lambda given: root if given is None else given)
    monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED","1")
    monkeypatch.delenv("KAUFLAND_APLERBECK_CAPTURE_SHA256",raising=False)
    url_path="/ui/home/booklet-assets/kaufland/large/69"
    with TestClient(app) as client:
        assert client.get(url_path).status_code==404
        monkeypatch.setenv("KAUFLAND_APLERBECK_CAPTURE_SHA256",digest)
        response=client.get(url_path)
        assert response.status_code==200
        assert response.content==(root/"pages/large/bk_69.jpg").read_bytes()
        assert response.headers["content-type"]=="image/jpeg"
        assert response.headers["cache-control"]=="private, no-store"
        assert response.headers["x-content-type-options"]=="nosniff"
        assert client.get("/ui/home/booklet-assets/kaufland/normal/70").status_code==404
        monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED","0")
        assert client.get(url_path).status_code==404
