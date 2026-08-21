from __future__ import annotations

import base64
from pathlib import Path
import struct

from fastapi.testclient import TestClient

from app.main import app
from tests.ui_contract import read_family_ui_contract, ui_response_contract


client = TestClient(app)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_readme_uses_versioned_project_logo_without_legacy_banner() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    logo = 'src="backend/app/ui/assets/deals-logo.svg"'
    legacy_banner = 'src="assets/branding/readme-banner.jpg"'
    heading = '<h1 align="center">Hermes Deals</h1>'

    assert logo in readme
    assert 'width="128" height="128"' in readme
    assert legacy_banner not in readme
    assert heading in readme
    assert readme.index(logo) < readme.index(heading)


def test_main_ui_uses_versioned_project_logo_and_favicons() -> None:
    response = client.get("/ui")

    assert response.status_code == 200
    assert response.text.count('src="/ui/assets/deals-logo.svg"') == 3
    assert response.text.count('<svg class="brand-leaf" hidden') == 2
    assert response.text.count('<svg class="weekly-brand-mark" hidden') == 1
    assert 'href="/ui/assets/deals-logo.png"' in response.text
    assert 'href="/ui/assets/deals-logo.ico"' in response.text
    assert response.text.count("hermes-branding-overlay:start") == 1
    assert "<style id=\"hermes-deals-branding\"" not in response.text


def test_main_ui_branding_overlay_preserves_current_ui_contract() -> None:
    response = client.get("/ui")

    assert ui_response_contract(response) == read_family_ui_contract()


def test_review_ui_references_png_and_ico_favicons() -> None:
    response = client.get("/ui/review")

    assert response.status_code == 200
    assert 'href="/ui/assets/deals-logo.png"' in response.text
    assert 'href="/ui/assets/deals-logo.ico"' in response.text
    assert response.text.count("hermes-branding-overlay:start") == 1
    assert "Lidl — Pārskatīšanas rinda" in response.text


def test_svg_branding_asset_is_explicit_and_immutable() -> None:
    response = client.get("/ui/assets/deals-logo.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert b"Hermes Deals project logo" in response.content
    assert b"data:image/png;base64," in response.content


def test_png_branding_asset_is_exact_embedded_96px_source() -> None:
    svg = client.get("/ui/assets/deals-logo.svg")
    png = client.get("/ui/assets/deals-logo.png")

    assert png.status_code == 200
    assert png.headers["content-type"].startswith("image/png")
    assert png.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert png.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png.content[16:24]) == (96, 96)

    marker = b'href="data:image/png;base64,'
    encoded = svg.content.split(marker, 1)[1].split(b'"', 1)[0]
    assert base64.b64decode(encoded, validate=True) == png.content


def test_ico_branding_asset_wraps_exact_approved_png() -> None:
    png = client.get("/ui/assets/deals-logo.png").content
    ico = client.get("/ui/assets/deals-logo.ico")

    assert ico.status_code == 200
    assert ico.headers["content-type"].startswith("image/x-icon")
    assert ico.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert ico.content[:6] == struct.pack("<HHH", 0, 1, 1)
    width, height, colors, reserved, planes, bits, size, offset = struct.unpack(
        "<BBBBHHII", ico.content[6:22]
    )
    assert (width, height, colors, reserved, planes, bits) == (96, 96, 0, 0, 1, 32)
    assert offset == 22
    assert size == len(png)
    assert ico.content[offset : offset + size] == png


def test_branding_asset_routes_are_allowlisted_not_catch_all() -> None:
    assert client.get("/ui/assets/deals-logo.svg").status_code == 200
    assert client.get("/ui/assets/deals-logo.png").status_code == 200
    assert client.get("/ui/assets/deals-logo.ico").status_code == 200
    assert client.get("/ui/assets/not-allowlisted.txt").status_code == 404

    paths = app.openapi().get("paths", {})
    assert "/ui/assets/deals-logo.svg" not in paths
    assert "/ui/assets/deals-logo.png" not in paths
    assert "/ui/assets/deals-logo.ico" not in paths
