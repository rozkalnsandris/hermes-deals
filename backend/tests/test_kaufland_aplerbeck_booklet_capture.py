"""Synthetic, network-free, first-party Kaufland 1503 capture tests."""
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


def signed(page, size=1200, seed="a"):
    original = f"s3://leaflets/images/{tool.FLYER_ID}/page-{page:02d}_{seed*32}.png"
    token = base64.urlsafe_b64encode(original.encode()).decode().rstrip("=")
    return f"{tool.CDN}{'X'*43}/rs:fit:{size}:{size}:1/g:no/{token}.jpg"


class Response:
    status = 200
    def __init__(self, url, body):
        self.url = url
        self.body = BytesIO(body)
        self.headers = {"Content-Type": "image/jpeg" if url.startswith(tool.CDN) else "text/html",
                        "Content-Length": str(len(body))}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, amount):
        return self.body.read(amount)


def fake(request, timeout, *, missing=None, conflicting=False, wrong_store=False):
    url = request.full_url
    if url == tool.SOURCE:
        raw = LANDING.replace(b"Kaufland Dortmund-Aplerbeck", b"Kaufland Duesseldorf") if wrong_store else LANDING
        return Response(url, raw)
    if url.startswith(tool.VIEWER_PAGE):
        n = int(url.removeprefix(tool.VIEWER_PAGE))
        assert n == 1 or n % 2 == 0
        body = "<html><title>Prospekt - 01.11.2026 - 07.11.2026</title>"
        if n == 1:
            body += "<span>1 / 70</span>"
        for page in ((1,) if n == 1 else tuple(x for x in (n, n+1) if x <= 70)):
            if page != missing:
                body += f'<img src="{signed(page)}">'
                if conflicting and page == 21:
                    body += f'<img src="{signed(page, seed="b")}">'
        return Response(url, (body + "</html>").encode())
    assert tool._original(url) is not None
    n = tool._original(url)[0]
    data = b"\xff\xd8\xff" + f"page-{n}:".encode() * 55 + b"\xff\xd9"
    return Response(url, data)


def test_signed_page_identity_and_decoding():
    assert tool._original(signed(1))[0] == 1
    assert tool._original(signed(1) + "?token=secret") is None
    assert tool._original(signed(1).replace("imgproxy.leaflets.schwarz", "evil.example")) is None
    urls = [signed(n).replace("/", "\\u002F") for n in (1,2)]
    assert set(tool._image_links(("<script>" + " ".join(urls) + "</script>").encode())) == {signed(1), signed(2)}


def test_complete_70_pages_140_images_candidate_only(tmp_path):
    meta, files = tool.capture(open_url=fake, now=CLOCK)
    assert meta["page_count"] == 70 and len(files) == 140
    assert meta["store_id"] == "1503" and meta["source_flyer_id"] == tool.FLYER_ID
    assert meta["expires_at"] == (CLOCK + timedelta(days=30)).isoformat()
    assert meta["publication_authorized"] is False and meta["pdf_retained"] is False
    assert files["pages/normal/bk_70.jpg"] == files["pages/large/bk_70.jpg"]
    output = tmp_path / "candidate"
    tool.save_new_output(output, meta, files)
    raw = (output / "capture.json").read_bytes()
    assert sha256(raw).hexdigest() and json.loads(raw)["pages"][-1]["number"] == 70
    assert len(list(output.glob("pages/*/*.jpg"))) == 140
    with pytest.raises(ValueError):
        tool.save_new_output(output, meta, files)


@pytest.mark.parametrize("missing", (1, 17, 70))
def test_missing_original_fails_before_writing(tmp_path, missing):
    with pytest.raises(ValueError, match="Missing verified first-party page"):
        tool.capture(open_url=lambda r, timeout: fake(r, timeout, missing=missing), now=CLOCK)
    assert not list(tmp_path.iterdir())


def test_conflicting_original_and_wrong_store_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="Conflicting original"):
        tool.capture(open_url=lambda r, timeout: fake(r, timeout, conflicting=True), now=CLOCK)
    with pytest.raises(ValueError, match="Wrong or unproven"):
        tool.capture(open_url=lambda r, timeout: fake(r, timeout, wrong_store=True), now=CLOCK)
    assert not list(tmp_path.iterdir())


def test_expired_window_rejected():
    with pytest.raises(ValueError, match="window"):
        tool.capture(open_url=fake, now=CLOCK + timedelta(days=8))


def test_unexpected_image_redirect_rejected():
    def redirect(request, timeout):
        response = fake(request, timeout)
        if request.full_url.startswith(tool.CDN):
            response.url = response.url.replace("imgproxy.leaflets.schwarz", "untrusted.example")
        return response
    with pytest.raises(ValueError, match="redirect"):
        tool.capture(open_url=redirect, now=CLOCK)


def test_higher_resolution_used_only_when_first_party_declares_it():
    htmls = [(f'<img src="{signed(n)}"><img src="{signed(n, 2400)}">').encode()
             for n in range(1, 71)]
    found = tool._choose_urls(htmls)
    assert found[1]["normal"] == signed(1)
    assert found[1]["large"] == signed(1, 2400)
    assert found[70]["large"] == signed(70, 2400)
