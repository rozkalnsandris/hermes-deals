from __future__ import annotations

from pathlib import Path

import pytest

import app.lidl_v631_c3_readonly_preflight as c3


FIXTURE = Path(__file__).parent / "fixtures/lidl/issue_620_full_semantic_row_landliebe.json.b64"


def test_reviewed_semantic_fixture_accepts_single_terminal_lf() -> None:
    encoded = FIXTURE.read_bytes()
    assert encoded.endswith(b"\n")
    assert not encoded.endswith(b"\n\n")

    row = c3.load_semantic_row(FIXTURE)

    assert row["product_name"] == "LANDLIEBE Butter"
    assert row["page"] == 19
    assert row["package_text"] == "250 g"
    assert row["price_eur"] == "1.39"
    assert row["regular_price_eur"] == "2.69"
    assert row["valid_from"] == "2026-08-10"
    assert row["valid_until"] == "2026-08-15"


def test_reviewed_semantic_fixture_rejects_more_than_one_terminal_lf(tmp_path: Path) -> None:
    candidate = tmp_path / "semantic-row.b64"
    candidate.write_bytes(FIXTURE.read_bytes() + b"\n")

    with pytest.raises(c3.LidlC3ReadonlyPreflightError, match="Base64 is invalid"):
        c3.load_semantic_row(candidate)
