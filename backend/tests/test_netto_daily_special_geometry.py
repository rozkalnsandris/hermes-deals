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
    Path(__file__).parent / "fixtures" / "netto_daily_special_hz32_hasb.json"
)
SNAPSHOT_ID = "3ab4cf87-c9fe-4457-972b-781f020a51f2"


def fixture_pages() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["pages"]


def blocks(page: dict) -> tuple[NettoPdfTextBlock, ...]:
    return tuple(
        NettoPdfTextBlock(text, x0, y0, x1, y1)
        for x0, y0, x1, y1, text in page["blocks"]
    )


class NettoDailySpecialGeometryTest(unittest.TestCase):
    def test_exact_hz32_daily_pages_have_explicit_date_and_geometry(self) -> None:
        pages = fixture_pages()
        self.assertEqual([page["page_number"] for page in pages], [12, 13, 41, 42])

        for fixture in pages:
            source_blocks = blocks(fixture)
            page = detect_daily_special_page(
                "\n".join(block.text for block in source_blocks),
                fixture["page_number"],
                source_blocks,
            )
            self.assertIsNotNone(page)
            assert page is not None
            self.assertEqual(page.special_valid_on, date.fromisoformat(fixture["date"]))
            self.assertTrue(page.special_source_geometry)
            self.assertIn("gültig am", page.special_source_text.casefold())

    def test_exact_hz32_product_cards_are_page_bound(self) -> None:
        for fixture in fixture_pages():
            source_blocks = blocks(fixture)
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
            self.assertEqual(
                [row.product_name_raw for row in rows],
                fixture["products"],
            )
            for row in rows:
                self.assertEqual(row.special_source_page, fixture["page_number"])
                self.assertEqual(row.special_valid_on, date.fromisoformat(fixture["date"]))
                self.assertGreater(row.price_eur, Decimal("0"))
                self.assertTrue(row.source_geometry)
                self.assertEqual(row.source_geometry[0]["role"], "product")
                self.assertEqual(row.source_geometry[1]["role"], "sale_price")

    def test_variable_weight_card_keeps_its_price_basis(self) -> None:
        fixture = fixture_pages()[2]
        source_blocks = blocks(fixture)
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
        pork = next(row for row in rows if row.product_name_raw == "Schweine-Bauch")
        self.assertEqual(pork.pricing_mode, "unit_price_only")
        self.assertEqual(pork.unit_label, "kg")
        self.assertEqual(pork.unit_price_eur, Decimal("3.99"))

    def test_ambiguous_package_without_a_price_is_not_published(self) -> None:
        fixture = fixture_pages()[0]
        source_blocks = blocks(fixture) + (
            NettoPdfTextBlock(
                "Unklare Ware\n250 g",
                20,
                500,
                120,
                560,
            ),
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
        self.assertEqual([row.product_name_raw for row in rows], ["Brombeeren"])


if __name__ == "__main__":
    unittest.main()
