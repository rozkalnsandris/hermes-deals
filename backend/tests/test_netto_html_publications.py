from datetime import date
import json

import httpx
import pytest

from app.netto_html_publications import fetch_one, validated_pages


VIEWER = "https://wochenprospekt.netto-online.de/hz45_hasb/?storeid=5659"
PUB = "https://api.publitas.com/v1/groups/netto/publications/hz45_hasb.json"
HTML = (
    '<meta name="description" content="Montag, 02.11.26 - Samstag, 07.11.26">'
    '<script>{"groupSlug":"netto"}</script>'
)
PUBLICATION = {"spreads": [{"pages": ["/netto/hz45/page-1", "/netto/hz45/page-2"]}]}


def source(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def good(request):
    url = str(request.url)
    if url == VIEWER:
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})
    if url == PUB:
        return httpx.Response(200, json=PUBLICATION)
    raise AssertionError("unexpected external request: " + url)


def test_metadata_requires_actual_official_validity_and_pages():
    requested = []
    def handler(req):
        requested.append(str(req.url))
        return good(req)
    with source(handler) as client:
        capture = fetch_one(client, "hz45_hasb", date(2026, 11, 2))
    assert requested == [VIEWER, PUB]
    assert (capture.start, capture.end) == (date(2026, 11, 2), date(2026, 11, 7))
    assert capture.viewer_url == VIEWER
    assert json.loads(capture.publication_json) == PUBLICATION


@pytest.mark.parametrize("bad_html", [
    "<html>No validity</html>",
    '<meta name="description" content="Montag, 09.11.26 - Samstag, 14.11.26"><script>{"groupSlug":"netto"}</script>',
    '<meta name="description" content="Montag, 02.11.26 - Samstag, 21.11.26"><script>{"groupSlug":"netto"}</script>',
    '<meta name="description" content="Montag, 02.11.26 - Samstag, 07.11.26"><script>{"groupSlug":"../../evil"}</script>',
])
def test_missing_conflicting_or_untrusted_viewer_fails_closed(bad_html):
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, text=bad_html, headers={"content-type": "text/html"})
    with source(handler) as client:
        with pytest.raises(ValueError):
            fetch_one(client, "hz45_hasb", date(2026, 11, 2))
    assert calls == [VIEWER]


@pytest.mark.parametrize("paths", [
    [], ["//external/asset"], ["/netto/../secrets"],
    ["https://example.invalid/1"], ["/same", "/same"],
])
def test_untrusted_or_missing_publication_pages_rejected(paths):
    with pytest.raises(ValueError):
        validated_pages({"spreads": [{"pages": paths}]})


def test_redirect_and_wrong_content_type_rejected_before_api():
    for status, headers in [
        (302, {"location": "https://evil.invalid/path"}),
        (200, {"content-type": "text/plain"}),
    ]:
        with source(lambda req: httpx.Response(status, text=HTML, headers=headers)) as client:
            with pytest.raises(ValueError):
                fetch_one(client, "hz45_hasb", date(2026, 11, 2))


def test_invalid_slug_never_requests_external_url():
    with source(lambda req: (_ for _ in ()).throw(AssertionError("network"))) as client:
        with pytest.raises(ValueError):
            fetch_one(client, "../leak", date(2026, 11, 2))
