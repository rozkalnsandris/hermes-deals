from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from app.main import app
from tests.ui_contract import (
    CSS_TRAILING_WS_PATCHES,
    JS_TRAILING_WS_PATCHES,
    ORIGINAL_INDEX_SHA256,
    UI_APP_PATH,
    UI_STYLE_PATH,
    read_family_ui_contract,
)


EXPECTED_CSS_SHA256 = "f02517db802d9e6a58ea22e35fc8ee2023308ce074474eea90d638b90aac1a88"
EXPECTED_JS_SHA256 = "fa2e6a982406a3a9248067d2277efa64f51219818dea5ef13f493a47e46efc53"


def test_ui_html_uses_external_static_assets() -> None:
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/ui/styles.css"' in response.text
    assert 'src="/ui/app.js"' in response.text
    assert "<style" not in response.text
    assert "<script>" not in response.text
    assert 'content="reference-v11-explicit-daily-special-api"' in response.text
    assert 'content="weekly-overview-v6-active-retailer-compaction"' in response.text
    assert 'content="netto-daily-quality-v1"' in response.text


def test_ui_stylesheet_route_and_content_identity() -> None:
    response = TestClient(app).get("/ui/styles.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert sha256(response.content).hexdigest() == EXPECTED_CSS_SHA256
    assert sha256(UI_STYLE_PATH.read_bytes()).hexdigest() == EXPECTED_CSS_SHA256
    assert b"--accent:#246b45" in response.content
    assert b"body.ui-minimal-v2" in response.content
    assert response.content.count(b"HERMES_UI_STYLE_OPEN:") == 12
    assert response.content.count(b"HERMES_UI_STYLE_CLOSE:") == 12
    assert response.content.count(b"HERMES_UI_STYLE_GAP:") == 11
    assert CSS_TRAILING_WS_PATCHES
    assert not any(
        line.endswith((b" ", b"\t"))
        for line in response.content.splitlines()
    )


def test_ui_application_route_and_content_identity() -> None:
    response = TestClient(app).get("/ui/app.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/javascript"
    )
    assert sha256(response.content).hexdigest() == EXPECTED_JS_SHA256
    assert sha256(UI_APP_PATH.read_bytes()).hexdigest() == EXPECTED_JS_SHA256
    assert response.content.count(b"HERMES_UI_SCRIPT_OPEN:") == 2
    assert response.content.count(b"HERMES_UI_SCRIPT_CLOSE:") == 2
    assert response.content.count(b"HERMES_UI_SCRIPT_GAP:") == 1
    assert not any(
        line.endswith((b" ", b"\t"))
        for line in response.content.splitlines()
    )
    assert isinstance(JS_TRAILING_WS_PATCHES, list)
    for marker in (
        b"/api/v1/deals/current",
        b"/api/v1/deals/daily-specials",
        b"/api/v1/catalog",
        b"URLSearchParams",
    ):
        assert marker in response.content


def test_legacy_contract_reconstructs_original_index_exactly() -> None:
    contract = read_family_ui_contract()

    assert sha256(contract.encode("utf-8")).hexdigest() == ORIGINAL_INDEX_SHA256
    assert ORIGINAL_INDEX_SHA256 == "fd8739e8e8605ff8c95bc2e728081d3cfdc0639d55e8546c3fd240d8c6d9d3cc"


def test_ui_trailing_slash_behavior_remains_routable() -> None:
    response = TestClient(app).get("/ui/", follow_redirects=False)

    assert response.status_code in {200, 307, 308}
