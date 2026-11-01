"""A registered ALDI booklet uses the existing reader, never fabricated offers."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json

import pytest

from app.aldi_verified_booklets import read_verified_aldi_booklet

DAY = date(2026, 11, 2)
CLOCK = datetime(2026, 11, 3, tzinfo=timezone.utc)
VIEWER = ("https://magazine.aldi-nord.de/aldi-nord/aldi-aktuell/2026/"
          "2026cw45mopromotionaldi-angebote-ab-montag-02-11-1/")


def manifest():
    def images(i, kind):
        return VIEWER + f"Image.ashx?PageNumber={i}&ImageType={kind}"
    return {
        "schema": "aldi_nord_verified_booklet_v1",
        "observed_at": "2026-11-01T09:52:31Z",
        "expires_at": "2026-12-01T09:52:31Z",
        "publications": [{
            "scope": "national_unbound", "valid_from": "2026-11-02", "valid_until": "2026-11-07",
            "viewer_url": VIEWER, "pdf_url": VIEWER + "/GetPDF.ashx",
            "pdf_sha256": "a" * 64, "pdf_bytes": 114790351, "page_count": 3,
            "pages": [{"number": i, "image_url": images(i, "Normal"),
                       "zoom_image_url": images(i, "Zoom")} for i in range(1, 4)],
        }],
    }


def register(tmp_path, obj):
    path = tmp_path / "verified-manifest.json"
    raw = (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


def read(tmp_path, digest, *, page=1, day=DAY, now=CLOCK):
    return read_verified_aldi_booklet(day, page, root=tmp_path,
                                      manifest_sha256=digest, now=now)


def test_undisclosed_digest_preserves_official_catalogue(monkeypatch, tmp_path):
    monkeypatch.delenv("ALDI_NORD_BOOKLET_MANIFEST_SHA256", raising=False)
    assert read_verified_aldi_booklet(DAY, root=tmp_path) is None


def test_registered_full_page_set_is_ready_with_netto_reader_contract(tmp_path):
    digest = register(tmp_path, manifest())
    first = read(tmp_path, digest)
    assert first["state"] == "ready"
    assert first["page_count"] == 3
    assert first["swipeable"] is True
    assert first["offers"] == []
    assert "filiāle nav piesaistīta" in first["store_name"]
    assert first["valid_label"] == "02.11.2026–07.11.2026"
    assert [entry["number"] for entry in first["pages"]] == [1, 2, 3]
    assert first["pages"][0]["zoom_image_url"].endswith("ImageType=Zoom")
    assert first["previous_href"] is None
    assert "retailer=aldi_nord" in first["next_href"]
    third = read(tmp_path, digest, page=3)
    assert third["previous_href"].endswith("retailer=aldi_nord")
    assert third["next_href"] is None
    assert read(tmp_path, digest, page=4)["state"] == "missing_page"
    assert read(tmp_path, digest, day=date(2026, 11, 8)) is None


def test_tamper_with_unchanged_registration_is_unavailable(tmp_path):
    digest = register(tmp_path, manifest())
    (tmp_path / "verified-manifest.json").write_text('{"unexpected":true}')
    assert read(tmp_path, digest)["state"] == "unavailable"
    assert read(tmp_path, "bad")["state"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("pdf_sha256", "bad"),
    ("pdf_bytes", 0),
    ("scope", "dortmund_assumed"),
    ("page_count", 2),
    ("valid_until", "2026-11-01"),
    ("viewer_url", "https://evil.example/reader/"),
])
def test_invalid_publication_fails_closed(tmp_path, field, value):
    obj = manifest()
    obj["publications"][0][field] = value
    assert read(tmp_path, register(tmp_path, obj))["state"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("number", 9),
    ("image_url", "https://evil.example/Image.ashx?PageNumber=1&ImageType=Normal"),
    ("image_url", VIEWER + "Image.ashx?PageNumber=2&ImageType=Normal"),
    ("image_url", VIEWER + "Image.ashx?PageNumber=1&ImageType=Zoom"),
    ("image_url", VIEWER + "Image.ashx?PageNumber=1&ImageType=Normal&token=secret"),
    ("zoom_image_url", VIEWER + "Image.ashx?PageNumber=1&ImageType=Normal"),
])
def test_page_identity_mismatch_fails_closed(tmp_path, field, value):
    obj = manifest()
    obj["publications"][0]["pages"][0][field] = value
    assert read(tmp_path, register(tmp_path, obj))["state"] == "unavailable"


def test_expired_or_future_dated_evidence_fails_closed(tmp_path):
    digest = register(tmp_path, manifest())
    assert read(tmp_path, digest, now=CLOCK + timedelta(days=40))["state"] == "unavailable"
    assert read(tmp_path, digest, now=CLOCK - timedelta(days=5))["state"] == "unavailable"


def test_duplicate_and_overlapping_publications_fail_closed(tmp_path):
    obj = manifest()
    obj["publications"].append(dict(obj["publications"][0]))
    assert read(tmp_path, register(tmp_path, obj))["state"] == "unavailable"


def test_missing_registered_manifest_not_a_live_catalogue_fallback(tmp_path):
    assert read(tmp_path, "a" * 64)["state"] == "unavailable"


def test_symlinked_registry_is_untrusted(tmp_path):
    original = tmp_path / "real"
    original.mkdir()
    digest = register(original, manifest())
    alias = tmp_path / "alias"
    alias.symlink_to(original, target_is_directory=True)
    assert read(alias, digest)["state"] == "unavailable"
