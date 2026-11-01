"""Synthetic, network-free EDEKA Patzer immutable capture boundary tests."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import importlib.util
import json

import pytest

PATH = Path(__file__).resolve().parents[2] / "tools/edeka_patzer_booklet_capture.py"
SPEC = importlib.util.spec_from_file_location("edeka_patzer_booklet_capture", PATH)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

CLOCK = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
LANDING = (
    '<html><h2>EDEKA Patzer</h2><a href="/maerkte/071897/">Markt</a>'
    '<p>Gültig vom 02.11.2026 bis zum 07.11.2026.</p>'
    f'<iframe src="{tool.VIEWER}"></iframe>'
    '<iframe src="https://blaetterkatalog.edeka.de/OTHER/SUUPER/index.html"></iframe>'
    '</html>'
).encode()


class Response:
    status = 200
    def __init__(self, url, body):
        self.url = url
        self.body = BytesIO(body)
        self.headers = {
            "Content-Type": "text/html" if url == tool.SOURCE else "image/jpeg",
            "Content-Length": str(len(body)),
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount):
        return self.body.read(amount)


def faux(url, timeout, *, rotated=False, wrong_market=False):
    url = url.full_url
    if url == tool.SOURCE:
        data = LANDING.replace(b"071897", b"071898") if wrong_market else LANDING
        return Response(url, data)
    if url.endswith("bk_35.jpg"):
        raise AssertionError("Capture must not probe beyond its pinned page list")
    number = int(url.rsplit("bk_", 1)[-1].removesuffix(".jpg"))
    quality = "normal" if "/normal/" in url else "large"
    body = b"\xff\xd8\xff" + f"{quality}:{number}:".encode() * 90 + b"\xff\xd9"
    if rotated and number == 34:
        body += b"new"
    return Response(url, body)


def test_pinned_capture_has_two_quality_sets_with_provenance():
    m, files = tool.capture(open_url=lambda request, timeout: faux(request, timeout), now=CLOCK)
    assert len(files) == 68 and len(m["pages"]) == 34
    assert m["page_count"] == 34
    assert m["source_market_id"] == "587881"
    assert m["scope"] == "family_primary_edeka"
    assert m["valid_from"] == "2026-11-02"
    assert m["valid_until"] == "2026-11-07"
    assert m["expires_at"] == (CLOCK + timedelta(days=30)).isoformat()
    assert m["state"] == "candidate_only_unregistered"
    assert m["publisher_urls_may_rotate"] is True
    assert m["pdf_retained"] is False
    assert m["pages"][-1]["large"]["source_url"].endswith("/large/bk_34.jpg")
    assert all(sha256(files[p["normal"]["path"]]).hexdigest() == p["normal"]["sha256"] for p in m["pages"])


def test_output_is_exclusive_and_verifies_each_file(tmp_path):
    m, files = tool.capture(open_url=lambda request, timeout: faux(request, timeout), now=CLOCK)
    destination = tmp_path / "new-evidence"
    tool.save_new_output(destination, m, files)
    saved = json.loads((destination / "capture.json").read_text())
    assert saved["page_count"] == 34
    assert len(list((destination / "pages" / "large").iterdir())) == 34
    assert (destination / "pages/normal/bk_01.jpg").is_file()
    with pytest.raises(ValueError):
        tool.save_new_output(destination, m, files)


def test_reject_wrong_market_binding():
    with pytest.raises(ValueError, match="Unbound"):
        tool.capture(open_url=lambda req, timeout: faux(req, timeout, wrong_market=True), now=CLOCK)


def test_reject_missing_prospect_or_different_week():
    with pytest.raises(ValueError):
        tool._verify_landing(LANDING.replace(tool.VIEWER.encode(), b"https://other.example/"))
    with pytest.raises(ValueError):
        tool._verify_landing(LANDING.replace(b"07.11.2026", b"14.11.2026"))


def test_pinned_capture_does_not_probe_unverifiable_page_35():
    requested = []
    def record(req, timeout):
        requested.append(req.full_url)
        return faux(req, timeout)

    manifest, files = tool.capture(open_url=record, now=CLOCK)
    assert manifest["page_count"] == 34
    assert len(files) == 68
    assert not any(url.endswith("bk_35.jpg") for url in requested)
    with pytest.raises(ValueError, match="Untrusted EDEKA page request"):
        tool.image_url(35, "normal")


def test_reject_expired_pinned_edition():
    with pytest.raises(ValueError, match="ended"):
        tool.capture(open_url=lambda req, timeout: faux(req, timeout), now=CLOCK + timedelta(days=9))


def test_invalid_jpeg_fails_closed():
    def bad(req, timeout):
        r = faux(req, timeout)
        if req.full_url.endswith("/normal/bk_2.jpg"):
            r.body = BytesIO(b"html not jpg")
        return r
    with pytest.raises(ValueError):
        tool.capture(open_url=bad, now=CLOCK)


def test_rotating_publisher_fails_closed():
    times = {}
    def changing(req, timeout):
        u = req.full_url
        times[u] = times.get(u, 0) + 1
        r = faux(req, timeout)
        if u.endswith("/large/bk_34.jpg") and times[u] > 1:
            r.body = BytesIO(b"\xff\xd8\xff" + b"changed"*120 + b"\xff\xd9")
        return r
    with pytest.raises(ValueError, match="rotated"):
        tool.capture(open_url=changing, now=CLOCK)


def test_untrusted_redirect_fails_closed():
    def redirect(req, timeout):
        r = faux(req, timeout)
        r.url = r.url.replace("blaetterkatalog.edeka.de", "third-party.example")
        return r
    with pytest.raises(ValueError, match="redirect"):
        tool.capture(open_url=redirect, now=CLOCK)
