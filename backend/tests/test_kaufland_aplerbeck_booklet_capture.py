"""Network-free, original Kaufland API-backed image capture tests."""
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "tools/kaufland_aplerbeck_booklet_capture.py"
spec = importlib.util.spec_from_file_location("kaufland_aplerbeck_capture", PATH)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
CLOCK = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
LANDING = (f'<main>Kaufland Dortmund-Aplerbeck Aplerbecker Marktplatz '
           f'<a href="{tool.VIEWER}">1503</a></main>').encode()


def signed(number, quality, *, source=None):
    if number == 69:
        original = tool.PROMOTION_ORIGINAL
        size = "rs:fill:729:1200:1" if quality == "normal" else "rs:fill:1458:2400:1"
    else:
        original = source or f"s3://leaflets/images/{tool.FLYER_ID}/page-{number:02d}_{'a'*32}.png"
        size = "rs:fit:1200:1200:1" if quality == "normal" else "rs:fit:2400:2400:1"
    token = base64.urlsafe_b64encode(original.encode()).decode().rstrip("=")
    return f"{tool.CDN}{'X'*43}/{size}/g:no/{token}.jpg"


def api(*, no_region=False, missing=None, wrong_type=None, alter=None):
    pages = []
    for number in range(1, tool.PAGES + 1):
        if number == missing:
            continue
        row = {
            "number": number, "type": "STANDARD" if number < 69 else "PROMOTION",
            "image": signed(number, "normal"),
            "zoom": signed(number, "large"),
        }
        if number == 69:
            row["promotionId"] = tool.PROMOTION_ID
        if number == wrong_type:
            row["type"] = "STANDARD" if number == 69 else "PROMOTION"
        if number == alter:
            row["zoom"] = signed(number, "normal")
        pages.append(row)
    return {
        "version": 4, "success": True,
        "flyer": {
            "id": tool.FLYER_ID, "startDate": tool.START, "endDate": tool.END,
            "title": "01.11.2026 - 07.11.2026", "isActive": True,
            "status": "current", "flyerUrlAbsolute": tool.VIEWER,
            "regions": [{"code": "1503"}] if not no_region else [{"code": "1800"}],
            "pages": pages,
        },
    }


class Response:
    status = 200

    def __init__(self, url, body):
        self.url = url
        self.body = BytesIO(body)
        kind = "application/json" if url == tool.API else (
            "image/jpeg" if url.startswith(tool.CDN) else "text/html")
        self.headers = {"Content-Type": kind, "Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount):
        return self.body.read(amount)


def fake(request, timeout, *, missing=None, no_region=False,
         wrong_type=None, alter=None, wrong_store=False, rotated=False):
    url = request.full_url
    if url == tool.SOURCE:
        landing = LANDING.replace(b"Kaufland Dortmund-Aplerbeck", b"Kaufland Koeln") if wrong_store else LANDING
        return Response(url, landing)
    if url == tool.API:
        manifest = api(missing=missing, no_region=no_region, wrong_type=wrong_type, alter=alter)
        if rotated:
            manifest["flyer"]["pages"][0]["image"] = signed(1, "normal", source=(
                f"s3://leaflets/images/{tool.FLYER_ID}/page-01_{'b'*32}.png"))
        return Response(url, json.dumps(manifest, sort_keys=True).encode())
    assert url.startswith(tool.CDN)
    for number in range(1, 70):
        for quality in tool.QUALITIES:
            if url == signed(number, quality):
                raw = b"\xff\xd8\xff" + f"page{number}-{quality}-".encode()*40 + b"\xff\xd9"
                return Response(url, raw)
    raise AssertionError(f"Unexpected source URL {url[:100]}")


def test_api_declares_68_original_pages_plus_one_promotion():
    published = tool._verify_api(json.dumps(api()).encode())
    assert len(published) == 69
    assert published[67]["type"] == "STANDARD"
    assert published[68]["type"] == "PROMOTION"
    assert published[68]["promotionId"] == tool.PROMOTION_ID
    assert tool._image_source(signed(68, "normal"), 68, "normal")
    assert tool._image_source(signed(69, "large"), 69, "large")
    assert not tool._image_source(signed(69, "large"), 69, "normal")
    assert not tool._image_source(signed(68, "normal"), 69, "normal")


def test_capture_persists_69_image_pages_and_138_jpegs(tmp_path):
    meta, files = tool.capture(open_url=fake, now=CLOCK)
    assert meta["page_count"] == 69 and len(files) == 138
    assert meta["store_id"] == "1503"
    assert meta["source_flyer_id"] == tool.FLYER_ID
    assert len(meta["api_json_sha256"]) == 64
    assert meta["expires_at"] == (CLOCK + timedelta(days=30)).isoformat()
    assert meta["pdf_retained"] is False and meta["publication_authorized"] is False
    assert files["pages/normal/bk_69.jpg"] != files["pages/large/bk_69.jpg"]
    out = tmp_path / "candidate"
    tool.save_new_output(out, meta, files)
    body = (out/"capture.json").read_bytes()
    assert sha256(body).hexdigest()
    assert json.loads(body)["pages"][-1]["number"] == 69
    assert len(list(out.glob("pages/*/*.jpg"))) == 138
    with pytest.raises(ValueError):
        tool.save_new_output(out, meta, files)


@pytest.mark.parametrize("missing", (1, 17, 69))
def test_missing_original_page_fails_before_storage(tmp_path, missing):
    with pytest.raises(ValueError, match="page count"):
        tool.capture(open_url=lambda request, timeout: fake(request, timeout, missing=missing), now=CLOCK)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("wrong_type", (33, 69))
def test_wrong_page_type_rejected(wrong_type):
    with pytest.raises(ValueError, match="page type|promotional page"):
        tool.capture(open_url=lambda request, timeout: fake(request, timeout, wrong_type=wrong_type), now=CLOCK)


def test_region_store_ownership_and_quality_fail_closed():
    with pytest.raises(ValueError, match="store region"):
        tool.capture(open_url=lambda request, timeout: fake(request, timeout, no_region=True), now=CLOCK)
    with pytest.raises(ValueError, match="Wrong or unproven"):
        tool.capture(open_url=lambda request, timeout: fake(request, timeout, wrong_store=True), now=CLOCK)
    with pytest.raises(ValueError, match="Untrusted page"):
        tool.capture(open_url=lambda request, timeout: fake(request, timeout, alter=22), now=CLOCK)


def test_no_capture_outside_pinned_edition():
    with pytest.raises(ValueError, match="window"):
        tool.capture(open_url=fake, now=CLOCK + timedelta(days=8))


def test_untrusted_image_redirect_rejected():
    def redirect(request, timeout):
        result = fake(request, timeout)
        if request.full_url.startswith(tool.CDN):
            result.url = result.url.replace("imgproxy.leaflets.schwarz", "evil.example")
        return result
    with pytest.raises(ValueError, match="redirect"):
        tool.capture(open_url=redirect, now=CLOCK)


def test_duplicate_metadata_keys_fail_closed():
    with pytest.raises(ValueError, match="Duplicate"):
        tool._verify_api(b'{"version":4,"version":4,"success":true,"flyer":{}}')
