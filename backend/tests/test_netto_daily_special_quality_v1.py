from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest

from app.parsers.netto_daily_special import (
    NettoPdfTextBlock,
    detect_daily_special_page,
    extract_geometry_candidates,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "netto_daily_special_real_pdf_pages_41_42.json"
)
SNAPSHOT_ID = "3ab4cf87-c9fe-4457-972b-781f020a51f2"


def saturday_rows():
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["pages"]
    fixture = next(row for row in fixtures if row["page_number"] == 42)
    source_blocks = tuple(
        NettoPdfTextBlock(text, x0, y0, x1, y1)
        for x0, y0, x1, y1, text in fixture["blocks"]
    )
    page = detect_daily_special_page(
        "\n".join(block.text for block in source_blocks),
        fixture["page_number"],
        source_blocks,
    )
    rows = extract_geometry_candidates(
        source_blocks,
        page,
        snapshot_id=SNAPSHOT_ID,
    )
    return {row.product_name_raw: row for row in rows}


def friday_rows():
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["pages"]
    fixture = next(row for row in fixtures if row["page_number"] == 41)
    source_blocks = tuple(
        NettoPdfTextBlock(text, x0, y0, x1, y1)
        for x0, y0, x1, y1, text in fixture["blocks"]
    )
    page = detect_daily_special_page(
        "\n".join(block.text for block in source_blocks),
        fixture["page_number"],
        source_blocks,
    )
    rows = extract_geometry_candidates(
        source_blocks,
        page,
        snapshot_id=SNAPSHOT_ID,
    )
    return {row.product_name_raw: row for row in rows}


class NettoDailySpecialQualityV1Test(unittest.TestCase):
    def test_fixture_is_exact_real_pdf_block_stream(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            fixture["source_contract"],
            "immutable Netto store 5659 PDF exact FitZ blocks",
        )
        self.assertEqual(len(fixture["pages"]), 2)
        page_counts = {
            row["page_number"]: len(row["blocks"])
            for row in fixture["pages"]
        }
        self.assertEqual(page_counts, {41: 82, 42: 57})
        self.assertEqual(
            fixture["source_page_text_sha256"]["42"],
            "b0c96971af239ff40afe2ff2d3ee04cd8af95cfc0ab07e7dfbaabc42ba222f1e",
        )

    def test_netto_plus_prices_are_bound_to_their_exact_cards(self) -> None:
        rows = saturday_rows()
        self.assertEqual(rows["Lillet L’Aperitif"].app_price_eur, Decimal("9.99"))
        self.assertEqual(rows["Softlan Weichspüler"].app_price_eur, Decimal("1.00"))

    def test_netto_plus_price_does_not_leak_to_neighbouring_cards(self) -> None:
        rows = saturday_rows()
        unexpected = {
            name: row.app_price_eur
            for name, row in rows.items()
            if name not in {"Lillet L’Aperitif", "Softlan Weichspüler"}
            and row.app_price_eur is not None
        }
        self.assertEqual(unexpected, {})

    def test_package_ranges_and_deposit_are_preserved(self) -> None:
        rows = saturday_rows()
        self.assertEqual(
            rows["Coppenrath & Wiese Meistertorte"].package_text_raw,
            "800 g – 1200 g",
        )
        self.assertEqual(rows["Milka Großtafel"].package_text_raw, "250 g – 300 g")
        self.assertEqual(
            rows["Softlan Weichspüler"].package_text_raw,
            "0,65 Liter – 1 Liter",
        )
        self.assertEqual(
            rows["Brinkhoff’s Premium Pilsener No.1 oder Alkoholfrei 0,0%"].deposit_eur,
            Decimal("3.10"),
        )

    def test_variable_weight_price_remains_explicitly_per_kilogram(self) -> None:
        pork = friday_rows()["Schweine-Bauch"]
        self.assertEqual(pork.special_valid_on, date(2026, 8, 7))
        self.assertEqual(pork.pricing_mode, "unit_price_only")
        self.assertEqual(pork.unit_price_eur, Decimal("3.99"))
        self.assertEqual(pork.unit_label, "kg")


if __name__ == "__main__":
    unittest.main()
