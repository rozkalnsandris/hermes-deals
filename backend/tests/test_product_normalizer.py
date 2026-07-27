from __future__ import annotations

from decimal import Decimal
import unittest

from app.product_normalizer import (
    brand_prefix_name_relation,
    extract_explicit_gtin,
    fuzzy_score,
    normalize_brand,
    normalize_gtin,
    normalize_offer_fields,
    normalize_text,
    package_relation,
    parse_edeka_image_package,
    parse_package_text,
    review_candidate_evidence,
)


class ProductNormalizerTest(unittest.TestCase):
    def _offer(self, **overrides):
        base = {
            "offer_candidate_id": "offer-1",
            "source_chain": "aldi_nord",
            "source_store_external_id": None,
            "source_offer_id": "source-1",
            "product_name_raw": "nimm2 Lachgummi XXL",
            "brand_raw": "STORCK",
            "package_text_raw": "Je 376 g",
            "raw_payload": {},
        }
        base.update(overrides)
        return normalize_offer_fields(**base)

    def test_normalize_text_preserves_numbers_and_german_letters(self):
        self.assertEqual(
            normalize_text("  Crème-Öl 1,5%  "),
            "crème öl 1 5%",
        )

    def test_normalize_brand_empty_becomes_none(self):
        self.assertIsNone(normalize_brand("   "))

    def test_single_grams_package(self):
        package = parse_package_text("Je 500g")
        self.assertEqual(package.item_quantity_value, Decimal("5E+2"))
        self.assertEqual(package.item_quantity_unit, "g")
        self.assertEqual(package.pack_count, 1)
        self.assertEqual(package.parse_method, "metric_single")

    def test_kilograms_convert_to_grams(self):
        package = parse_package_text("1,5 kg")
        self.assertEqual(package.item_quantity_value, Decimal("1.5E+3"))
        self.assertEqual(package.item_quantity_unit, "g")

    def test_liters_convert_to_milliliters(self):
        package = parse_package_text("0,75 l")
        self.assertEqual(package.item_quantity_value, Decimal("7.5E+2"))
        self.assertEqual(package.item_quantity_unit, "ml")

    def test_multipack_keeps_per_item_quantity_and_pack_count(self):
        package = parse_package_text("6 x 1 l")
        self.assertEqual(package.item_quantity_value, Decimal("1E+3"))
        self.assertEqual(package.item_quantity_unit, "ml")
        self.assertEqual(package.pack_count, 6)

    def test_piece_count_is_conservative(self):
        package = parse_package_text("10 Stück")
        self.assertIsNone(package.item_quantity_value)
        self.assertEqual(package.item_quantity_unit, "piece")
        self.assertEqual(package.pack_count, 10)

    def test_unknown_package_stays_unknown(self):
        package = parse_package_text("XXL Vorteilspack")
        self.assertIsNone(package.item_quantity_value)
        self.assertIsNone(package.item_quantity_unit)
        self.assertIsNone(package.pack_count)

    def test_gtin_checksum_accepts_valid_ean13(self):
        self.assertEqual(
            normalize_gtin("4006381333931"),
            "04006381333931",
        )

    def test_gtin_checksum_rejects_invalid_digits(self):
        self.assertIsNone(normalize_gtin("4006381333932"))

    def test_explicit_gtin_key_is_required(self):
        gtin, evidence = extract_explicit_gtin(
            {
                "image": "4006381333931.jpg",
                "objectID": "4006381333931",
            }
        )
        self.assertIsNone(gtin)
        self.assertIsNone(evidence)

    def test_nested_explicit_gtin_is_evidence(self):
        gtin, evidence = extract_explicit_gtin(
            {"product": {"ean": "4006381333931"}}
        )
        self.assertEqual(gtin, "04006381333931")
        self.assertEqual(evidence["key_path"], "$.product.ean")

    def test_package_conflict_is_hard_relation(self):
        left = self._offer(package_text_raw="100 g")
        right = self._offer(
            offer_candidate_id="offer-2",
            source_chain="edeka",
            package_text_raw="200 g",
        )
        self.assertEqual(package_relation(left, right), "conflict")

    def test_fuzzy_score_is_candidate_signal_not_boolean_truth(self):
        score, jaccard, sequence = fuzzy_score(
            "nimm2 Lachgummi XXL",
            "nimm2 Lachgummi",
        )
        self.assertGreater(score, 0.70)
        self.assertGreater(jaccard, 0.60)
        self.assertGreater(sequence, 0.70)


if __name__ == "__main__":
    unittest.main()


class ProductNormalizerV11EvidenceTest(unittest.TestCase):
    def _offer(self, **overrides):
        base = {
            "offer_candidate_id": "offer-v11-a",
            "source_chain": "aldi_nord",
            "source_store_external_id": None,
            "source_offer_id": "source-v11-a",
            "product_name_raw": "Alpenfrischkäse",
            "brand_raw": "Almette",
            "package_text_raw": "150-g-Becher",
            "raw_payload": {},
            "source_image_url": None,
        }
        base.update(overrides)
        return normalize_offer_fields(**base)

    def test_hyphenated_grams_are_parsed(self):
        package = parse_package_text("150-g-Becher")
        self.assertEqual(package.item_quantity_value, Decimal("1.5E+2"))
        self.assertEqual(package.item_quantity_unit, "g")
        self.assertEqual(package.pack_count, 1)

    def test_hyphenated_decimal_liters_are_parsed(self):
        package = parse_package_text("0,75-L-Flasche")
        self.assertEqual(package.item_quantity_value, Decimal("7.5E+2"))
        self.assertEqual(package.item_quantity_unit, "ml")

    def test_hyphenated_metric_multipack_is_parsed(self):
        package = parse_package_text("5x180-g-Packung")
        self.assertEqual(package.item_quantity_value, Decimal("1.8E+2"))
        self.assertEqual(package.item_quantity_unit, "g")
        self.assertEqual(package.pack_count, 5)

    def test_hyphenated_ml_multipack_is_parsed(self):
        package = parse_package_text("12x95-ml-Packung")
        self.assertEqual(package.item_quantity_value, Decimal("95"))
        self.assertEqual(package.item_quantity_unit, "ml")
        self.assertEqual(package.pack_count, 12)

    def test_count_only_pack_is_parsed_as_piece_count(self):
        package = parse_package_text("30er-Packung")
        self.assertIsNone(package.item_quantity_value)
        self.assertEqual(package.item_quantity_unit, "piece")
        self.assertEqual(package.pack_count, 30)
        self.assertEqual(package.parse_method, "count_pack")

    def test_count_only_roll_is_parsed_as_piece_count(self):
        package = parse_package_text("35er-Rolle")
        self.assertEqual(package.item_quantity_unit, "piece")
        self.assertEqual(package.pack_count, 35)

    def test_exact_stueck_is_one_piece(self):
        package = parse_package_text("Stück")
        self.assertEqual(package.item_quantity_unit, "piece")
        self.assertEqual(package.pack_count, 1)

    def test_generic_packung_stays_unknown(self):
        package = parse_package_text("Packung")
        self.assertIsNone(package.item_quantity_value)
        self.assertIsNone(package.item_quantity_unit)
        self.assertIsNone(package.pack_count)

    def test_kg_preis_marks_variable_weight_without_inventing_quantity(self):
        package = parse_package_text("kg-Preis")
        self.assertIsNone(package.item_quantity_value)
        self.assertIsNone(package.item_quantity_unit)
        self.assertIsNone(package.pack_count)
        self.assertEqual(package.parse_method, "variable_weight_kg_price")

    def test_edeka_image_single_metric_package(self):
        package = parse_edeka_image_package(
            "https://offer-images.api.edeka/"
            "951983c2-735b-40a2-9499-9a516a4c44db_"
            "Almette_Kraeuter_70Prz_150g_146503009.png"
        )
        self.assertEqual(package.item_quantity_value, Decimal("1.5E+2"))
        self.assertEqual(package.item_quantity_unit, "g")
        self.assertEqual(package.pack_count, 1)

    def test_edeka_image_multipack_package(self):
        package = parse_edeka_image_package(
            "https://offer-images.api.edeka/"
            "61327a63-5975-41f2-86b1-7cbebf321edf_"
            "Bio_Andechser_Natur_Joghurt_Himbeer_3_7_4x100g_1348762003.png"
        )
        self.assertEqual(package.item_quantity_value, Decimal("1E+2"))
        self.assertEqual(package.item_quantity_unit, "g")
        self.assertEqual(package.pack_count, 4)

    def test_edeka_image_underscore_decimal_multipack(self):
        package = parse_edeka_image_package(
            "https://offer-images.api.edeka/"
            "cfac7600-696c-4a88-8e69-39bade0040a7_"
            "Astra_Urtyp_27x0_33l.png"
        )
        self.assertEqual(package.item_quantity_value, Decimal("3.3E+2"))
        self.assertEqual(package.item_quantity_unit, "ml")
        self.assertEqual(package.pack_count, 27)

    def test_explicit_package_text_beats_edeka_image_fallback(self):
        offer = self._offer(
            source_chain="edeka",
            package_text_raw="200 g",
            source_image_url=(
                "https://offer-images.api.edeka/"
                "951983c2-735b-40a2-9499-9a516a4c44db_"
                "Almette_Kraeuter_70Prz_150g_146503009.png"
            ),
        )
        self.assertEqual(offer.item_quantity_value, Decimal("2E+2"))
        self.assertEqual(offer.package_evidence_source, "package_text_raw")

    def test_brand_prefix_exact_relation_is_detected(self):
        left = self._offer()
        right = self._offer(
            offer_candidate_id="offer-v11-b",
            source_chain="edeka",
            product_name_raw="Almette Alpenfrischkäse",
            brand_raw=None,
            package_text_raw=None,
            source_image_url=(
                "https://offer-images.api.edeka/"
                "951983c2-735b-40a2-9499-9a516a4c44db_"
                "Almette_Kraeuter_70Prz_150g_146503009.png"
            ),
        )
        relation = brand_prefix_name_relation(left, right)
        self.assertEqual(relation["brand"], "almette")

    def test_brand_prefix_exact_with_matching_package_is_review_candidate(self):
        left = self._offer()
        right = self._offer(
            offer_candidate_id="offer-v11-b",
            source_chain="edeka",
            product_name_raw="Almette Alpenfrischkäse",
            brand_raw=None,
            package_text_raw=None,
            source_image_url=(
                "https://offer-images.api.edeka/"
                "951983c2-735b-40a2-9499-9a516a4c44db_"
                "Almette_Kraeuter_70Prz_150g_146503009.png"
            ),
        )
        candidate = review_candidate_evidence(left, right)
        self.assertEqual(
            candidate["method"],
            "brand_prefix_name_exact_package_review",
        )
        self.assertEqual(candidate["package_relation"], "exact")

    def test_nimm2_legacy_dual_threshold_is_restored_as_review_only(self):
        left = self._offer(
            product_name_raw="nimm2 Lachgummi XXL",
            brand_raw="STORCK",
            package_text_raw="376-g-Packung",
        )
        right = self._offer(
            offer_candidate_id="offer-v11-b",
            source_chain="edeka",
            product_name_raw="nimm2 Lachgummi",
            brand_raw=None,
            package_text_raw=None,
        )
        candidate = review_candidate_evidence(left, right)
        self.assertEqual(
            candidate["method"],
            "legacy_dual_threshold_review",
        )
        self.assertLess(candidate["score"], 0.82)
