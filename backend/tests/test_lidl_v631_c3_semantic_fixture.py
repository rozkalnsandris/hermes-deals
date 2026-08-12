from __future__ import annotations

import base64
import json
from pathlib import Path

import app.lidl_v631_c3_readonly_preflight as c3


FIXTURE = Path(__file__).parent / "fixtures/lidl/issue_620_full_semantic_row_landliebe.json.b64"
EXPECTED_ROW_KEY = "dc83d8fb7156f7e7e48eccb01f0ade4c744308c69c4caad9f3afee53305a4669"


def test_landliebe_semantic_fixture_is_canonical_strict_base64() -> None:
    encoded = FIXTURE.read_bytes()

    assert encoded
    assert encoded == encoded.strip()

    decoded = base64.b64decode(encoded, validate=True)
    row = json.loads(decoded.decode("utf-8"))

    assert c3.load_semantic_row(FIXTURE) == row
    assert row["semantic_row_key"] == EXPECTED_ROW_KEY
    assert row["product_name"] == "LANDLIEBE Butter"
    assert row["page"] == 19
    assert row["package_text"] == "250 g"
    assert row["price_eur"] == "1.39"
    assert row["regular_price_eur"] == "2.69"
    assert row["valid_from"] == "2026-08-10"
    assert row["valid_until"] == "2026-08-15"
