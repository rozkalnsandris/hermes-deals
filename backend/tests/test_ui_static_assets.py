from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from app.main import app
from tests.ui_contract import (
    CSS_TRAILING_WS_PATCHES,
    JS_TRAILING_WS_PATCHES,
    UI_APP_PATH,
    UI_STYLE_PATH,
    UI_WEEKLY_BRIDGE_PATH,
    read_family_ui_contract,
)


EXPECTED_CSS_SHA256 = "f3910ab28599b1c418d0ab25986d6b112daf1c4e1b0d85e2d7faf409610a8e10"
EXPECTED_JS_SHA256 = "5e8e7b2f94a8ba9cca4e22be5ed0c189e996f40d137231fa27ca34e9efcd7b04"
EXPECTED_WEEKLY_BRIDGE_SHA256 = "6501a7ae2d3998ce1716c6710d97e7afcbac2d493991c2cdd6ebe57b324976fe"


def test_ui_html_uses_external_static_assets_without_historical_fix_metadata() -> None:
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/ui/styles.css"' in response.text
    assert 'src="/ui/weekly-payload-bridge.js"' in response.text
    assert 'src="/ui/app.js"' in response.text
    assert response.text.index('src="/ui/weekly-payload-bridge.js"') < response.text.index(
        'src="/ui/app.js"'
    )
    assert "<style" not in response.text
    assert "<script>" not in response.text
    assert '<meta name="hermes-ui-bundle" content="minimal-v2">' in response.text
    assert '<meta name="hermes-ui-release" content="reference-v1">' in response.text
    assert 'data-ui-release="reference-v1"' in response.text
    assert 'name="hermes-ui-fix"' not in response.text


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


def test_ui_weekly_payload_bridge_route_and_content_identity() -> None:
    response = TestClient(app).get("/ui/weekly-payload-bridge.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/javascript"
    )
    assert sha256(response.content).hexdigest() == EXPECTED_WEEKLY_BRIDGE_SHA256
    assert sha256(UI_WEEKLY_BRIDGE_PATH.read_bytes()).hexdigest() == EXPECTED_WEEKLY_BRIDGE_SHA256
    for marker in (
        b"/api/v1/deals/weekly-specials/ui",
        b"normalized_unique_deals_by_id_v1",
        b"deal_ids",
        b"new Proxy(response",
        b"return { ...payload, days }",
    ):
        assert marker in response.content
    assert not any(
        line.endswith((b" ", b"\t"))
        for line in response.content.splitlines()
    )


def test_split_asset_contract_reconstructs_current_ui_without_archaeology() -> None:
    contract = read_family_ui_contract()

    assert '<meta name="hermes-ui-bundle" content="minimal-v2">' in contract
    assert '<meta name="hermes-ui-release" content="reference-v1">' in contract
    assert 'data-ui-release="reference-v1"' in contract
    assert 'name="hermes-ui-fix"' not in contract
    assert 'id="weeklyOverviewTitle"' in contract
    assert 'id="dailySpecialsSection"' in contract


def test_ui_trailing_slash_behavior_remains_routable() -> None:
    response = TestClient(app).get("/ui/", follow_redirects=False)

    assert response.status_code in {200, 307, 308}
