"""Synthetic EDEKA image capture reader tests: no network or LIVE data."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest
from app import edeka_verified_booklets as v

DAY = date(2026, 11, 2)
CLOCK = datetime(2026, 11, 3, tzinfo=timezone.utc)


def capture(tmp_path):
    root = tmp_path / "edeka-booklets"
    root.mkdir()
    pages = []
    for n in range(1, v.COUNT + 1):
        row = {"number": n}
        for q in v.QUALITIES:
            folder = root / "pages" / q
            folder.mkdir(parents=True, exist_ok=True)
            data = b"\xff\xd8\xff" + (f"{n}:{q}:".encode() * 75) + b"\xff\xd9"
            (folder / f"bk_{n:02d}.jpg").write_bytes(data)
            row[q] = {"path": f"pages/{q}/bk_{n:02d}.jpg",
                      "source_url": f"{v.IMAGE_BASE}{q}/bk_{n}.jpg",
                      "bytes": len(data), "sha256": sha256(data).hexdigest()}
        pages.append(row)
    meta = {
        "schema": v.SCHEMA, "retailer": "edeka",
        "public_market_code": "071897", "source_market_id": "587881",
        "scope": "family_primary_edeka", "source_page": v.SOURCE,
        "source_html_sha256": "a" * 64, "viewer_url": v.VIEWER,
        "valid_from": "2026-11-02", "valid_until": "2026-11-07",
        "page_count": 34, "pages": pages,
        "observed_at": "2026-11-01T12:00:00+00:00",
        "expires_at": "2026-12-01T12:00:00+00:00",
        "state": "candidate_only_unregistered",
        "publisher_urls_may_rotate": True,
        "pdf_retained": False, "publication_authorized": False,
    }
    return root, meta


def register(root, meta):
    raw = (json.dumps(meta, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (root / "capture.json").write_bytes(raw)
    return sha256(raw).hexdigest()


def read(root, digest, **kwargs):
    return v.read_verified_edeka_booklet(DAY, root=root,
        manifest_sha256=digest, now=CLOCK, **kwargs)


def test_without_registration_is_unavailable_and_not_image_serving(monkeypatch, tmp_path):
    monkeypatch.delenv("EDEKA_PATZER_CAPTURE_SHA256", raising=False)
    assert v.read_verified_edeka_booklet(DAY, root=tmp_path) is None
    with pytest.raises(ValueError):
        v.read_verified_edeka_image(1, "normal", root=tmp_path)


def test_complete_sha_registered_pages_match_existing_ui_contract(tmp_path):
    root, meta = capture(tmp_path)
    digest = register(root, meta)
    page = read(root, digest)
    assert page["state"] == "ready" and page["offers"] == []
    assert page["page_count"] == 34 and page["swipeable"]
    assert page["image_url"] == "/ui/home/booklet-assets/edeka/normal/1"
    assert page["pages"][-1]["zoom_image_url"] == "/ui/home/booklet-assets/edeka/large/34"
    assert page["previous_href"] is None and "retailer=edeka" in page["next_href"]
    assert read(root, digest, page=34)["next_href"] is None
    assert read(root, digest, page=35)["state"] == "missing_page"
    assert v.read_verified_edeka_booklet(date(2026, 11, 8), root=root,
        manifest_sha256=digest, now=CLOCK) is None
    assert v.read_verified_edeka_image(34, "large", root=root,
        manifest_sha256=digest, now=CLOCK) == (root / "pages/large/bk_34.jpg").read_bytes()


@pytest.mark.parametrize(("field", "value"), [
    ("public_market_code", "071898"), ("scope", "wrong"),
    ("source_market_id", "other"), ("viewer_url", "https://evil.example/"),
    ("valid_until", "2026-11-14"), ("page_count", 33),
    ("pdf_retained", True), ("publication_authorized", True),
    ("state", "ready"), ("expires_at", "2027-01-01T12:00:00+00:00"),
])
def test_wrong_provenance_or_retention_fails_closed(tmp_path, field, value):
    root, meta = capture(tmp_path)
    meta[field] = value
    assert read(root, register(root, meta))["state"] == "unavailable"


@pytest.mark.parametrize(("field", "value"), [
    ("path", "../other.jpg"), ("source_url", "https://evil.example/a.jpg"),
    ("sha256", "bad"), ("bytes", 5),
])
def test_wrong_page_metadata_fails_closed(tmp_path, field, value):
    root, meta = capture(tmp_path)
    meta["pages"][0]["normal"][field] = value
    assert read(root, register(root, meta))["state"] == "unavailable"


def test_missing_tampered_or_symlinked_file_fails_closed(tmp_path):
    root, meta = capture(tmp_path)
    digest = register(root, meta)
    target = root / "pages/large/bk_34.jpg"
    target.write_bytes(b"\xff\xd8\xff" + b"changed" * 90 + b"\xff\xd9")
    assert read(root, digest)["state"] == "unavailable"
    with pytest.raises(ValueError):
        v.read_verified_edeka_image(34, "large", root=root,
            manifest_sha256=digest, now=CLOCK)
    target.unlink()
    assert read(root, digest)["state"] == "unavailable"
    target.symlink_to(root / "pages/normal/bk_34.jpg")
    assert read(root, digest)["state"] == "unavailable"


def test_invalid_manifest_expiry_symlink_and_page_inputs(tmp_path):
    root, meta = capture(tmp_path)
    digest = register(root, meta)
    assert v.read_verified_edeka_booklet(DAY, root=root, manifest_sha256=digest,
        now=CLOCK + timedelta(days=40))["state"] == "unavailable"
    assert v.read_verified_edeka_booklet(DAY, root=root, manifest_sha256=digest,
        now=CLOCK - timedelta(days=4))["state"] == "unavailable"
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert read(alias, digest)["state"] == "unavailable"
    assert read(root, "invalid")["state"] == "unavailable"
    for n, q in [(0, "normal"), (35, "large"), (1, "../large"), (True, "normal")]:
        with pytest.raises(ValueError):
            v.read_verified_edeka_image(n, q, root=root, manifest_sha256=digest, now=CLOCK)
    (root / "capture.json").write_text('{"schema": "untrusted"}')
    assert read(root, digest)["state"] == "unavailable"


def test_duplicate_manifest_fields_rejected(tmp_path):
    root, _ = capture(tmp_path)
    raw = b'{"schema":"x","schema":"y"}'
    (root / "capture.json").write_bytes(raw)
    assert read(root, sha256(raw).hexdigest())["state"] == "unavailable"


def test_private_image_route_serves_only_sha_verified_local_bytes(tmp_path, monkeypatch):
    """Actual HTTP route must not expose missing, expired or altered assets."""
    from fastapi.testclient import TestClient
    from app.main import app

    root, meta = capture(tmp_path)
    digest = register(root, meta)
    monkeypatch.setattr(v, "_root", lambda given: root if given is None else given)
    monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", "1")
    monkeypatch.delenv("EDEKA_PATZER_CAPTURE_SHA256", raising=False)
    url = "/ui/home/booklet-assets/edeka/large/34"

    with TestClient(app) as client:
        assert client.get(url).status_code == 404

        monkeypatch.setenv("EDEKA_PATZER_CAPTURE_SHA256", digest)
        image = client.get(url)
        assert image.status_code == 200
        assert image.content == (root / "pages/large/bk_34.jpg").read_bytes()
        assert image.headers["content-type"] == "image/jpeg"
        assert image.headers["cache-control"] == "private, no-store"
        assert image.headers["x-content-type-options"] == "nosniff"
        assert client.get("/ui/home/booklet-assets/edeka/normal/35").status_code == 404
        assert client.get("/ui/home/booklet-assets/edeka/other/1").status_code == 404

        (root / "pages/large/bk_34.jpg").write_bytes(b"\xff\xd8\xff" + b"corrupt" * 100 + b"\xff\xd9")
        assert client.get(url).status_code == 404

        monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", "0")
        assert client.get(url).status_code == 404
