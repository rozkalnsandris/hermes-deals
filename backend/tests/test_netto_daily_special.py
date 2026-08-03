import re
import unittest
from datetime import date
from decimal import Decimal

from app.parsers.netto_daily_special import (
    detect_daily_special_page,
    extract_food_milk_candidates,
    normalise_banner_text,
    parse_german_date,
)


SATURDAY_FIXTURE = """
SAMSTAGSSAMSTAGS
KRACHERKRACHER
gültig am Samstag,
01.08.26
Gutes
Land
Haltbare
Weide-
milch
3,5% Fett
12 x 1 Liter
(0.75 / l)
Einzelpreis:
0.95
9.–
*
11.40
12 für
–21%
"""

FRIDAY_FIXTURE = """
FREITAGS
53% SPAREN
und zusätzlich °punkten
gültig am 31.07.26
Hähnchen-Schenkel
1,1 kg
3.49
"""

SUN_MILK_FIXTURE = """
SAMSTAGS KRACHER
gültig am Samstag, 01.08.26
Sonnenmilch
LSF 30
250 ml
2.75
"""


class NettoDailySpecialShadowV2Test(unittest.TestCase):
    def test_duplicate_banner_words_are_normalised(self):
        value = normalise_banner_text(SATURDAY_FIXTURE)
        self.assertIn("SAMSTAGS", value)
        self.assertIn("KRACHER", value)
        self.assertNotIn("SAMSTAGSSAMSTAGS", value)
        self.assertNotIn("KRACHERKRACHER", value)

    def test_two_digit_german_date_is_parsed(self):
        self.assertEqual(
            parse_german_date("01.08.26"),
            date(2026, 8, 1),
        )

    def test_saturday_page_is_detected(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        self.assertIsNotNone(page)
        self.assertEqual(page.page_number, 17)
        self.assertEqual(page.special_valid_on, date(2026, 8, 1))
        self.assertEqual(page.special_type, "saturday_special")
        self.assertEqual(page.special_confidence, "high")

    def test_friday_page_is_detected(self):
        page = detect_daily_special_page(FRIDAY_FIXTURE, 15)
        self.assertIsNotNone(page)
        self.assertEqual(page.special_valid_on, date(2026, 7, 31))
        self.assertEqual(page.special_type, "weekday_special")

    def test_date_without_daily_banner_is_rejected(self):
        self.assertIsNone(
            detect_daily_special_page(
                "Normāls piedāvājums gültig am 01.08.26",
                4,
            )
        )

    def test_milk_candidate_requires_detected_daily_page(self):
        self.assertEqual(
            extract_food_milk_candidates(
                SATURDAY_FIXTURE,
                None,
                snapshot_id="snapshot",
            ),
            [],
        )

    def test_food_milk_candidate_is_extracted(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        rows = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].product_name_raw,
            "Gutes Land Haltbare Weidemilch 3.5% Fett",
        )

    def test_package_is_extracted(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        row = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        self.assertEqual(row.package_text_raw, "12 x 1 Liter")
        self.assertEqual(row.bundle_quantity, 12)

    def test_bundle_and_regular_prices_are_extracted(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        row = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        self.assertEqual(row.price_eur, Decimal("9"))
        self.assertEqual(row.regular_price_eur, Decimal("11.40"))

    def test_single_price_is_preserved(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        row = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        self.assertEqual(row.single_price_eur, Decimal("0.95"))

    def test_unit_price_is_preserved(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        row = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        self.assertEqual(row.unit_price_eur, Decimal("0.75"))

    def test_daily_validity_and_pdf_provenance_are_preserved(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        row = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        self.assertTrue(row.is_daily_special)
        self.assertEqual(row.valid_from, date(2026, 8, 1))
        self.assertEqual(row.valid_until, date(2026, 8, 1))
        self.assertEqual(row.special_source_kind, "prospect_pdf_page")
        self.assertEqual(row.special_source_page, 17)
        self.assertEqual(row.special_confidence, "high")

    def test_source_offer_id_is_deterministic(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        first = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        second = extract_food_milk_candidates(
            SATURDAY_FIXTURE,
            page,
            snapshot_id="snapshot",
        )[0]
        self.assertEqual(first.source_offer_id, second.source_offer_id)
        self.assertRegex(
            first.source_offer_id,
            r"^netto-daily-[0-9a-f]{32}$",
        )

    def test_non_food_sun_milk_is_rejected(self):
        page = detect_daily_special_page(SUN_MILK_FIXTURE, 56)
        self.assertIsNotNone(page)
        self.assertEqual(
            extract_food_milk_candidates(
                SUN_MILK_FIXTURE,
                page,
                snapshot_id="snapshot",
            ),
            [],
        )

    def test_source_text_contains_daily_banner_and_date(self):
        page = detect_daily_special_page(SATURDAY_FIXTURE, 17)
        self.assertIn("SAMSTAGS", page.special_source_text)
        self.assertIn("KRACHER", page.special_source_text)
        self.assertIn("01.08.26", page.special_source_text)


if __name__ == "__main__":
    unittest.main()
