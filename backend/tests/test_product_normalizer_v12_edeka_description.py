from __future__ import annotations

from decimal import Decimal
import unittest

from app.product_normalizer import (
    NORMALIZER_VERSION,
    normalize_offer_fields,
    parse_edeka_description_package,
)


class ProductNormalizerV12EdekaDescriptionTest(unittest.TestCase):
    def _offer(self, **overrides):
        base = {
            "offer_candidate_id": "offer-v12",
            "source_chain": "edeka",
            "source_store_external_id": "071897",
            "source_offer_id": "source-v12",
            "product_name_raw": "Example",
            "brand_raw": None,
            "package_text_raw": None,
            "raw_payload": {},
            "source_image_url": None,
        }
        base.update(overrides)
        return normalize_offer_fields(**base)

    def test_version_is_v12(self):
        self.assertEqual(NORMALIZER_VERSION, "normalizer-v1.2")

    def test_cevapcici_description_strips_unit_price(self):
        package = parse_edeka_description_package(
            {"description": "600 g Packung, (1 kg = € 9.98)"}
        )
        self.assertEqual(package.signature(), ("600", "g", 1))
        self.assertEqual(package.evidence_source, "raw_payload.description")

    def test_blueberry_description_parses_500g(self):
        package = parse_edeka_description_package(
            {"description": "aus Deutschland oder Polen, Klasse I, 500g"}
        )
        self.assertEqual(package.signature(), ("500", "g", 1))

    def test_barilla_description_parses_500g(self):
        package = parse_edeka_description_package(
            {"description": "versch. Ausformungen, 500g"}
        )
        self.assertEqual(package.signature(), ("500", "g", 1))

    def test_chicken_description_parses_1kg(self):
        package = parse_edeka_description_package(
            {"description": "Handelsklasse A, je 1 kg"}
        )
        self.assertEqual(package.signature(), ("1000", "g", 1))

    def test_ambiguous_multiple_metric_values_stay_unknown(self):
        package = parse_edeka_description_package(
            {"description": "wahlweise 250 g oder 500 g"}
        )
        self.assertEqual(package.signature(), (None, None, None))
        self.assertIsNone(package.parse_method)

    def test_package_text_precedes_description(self):
        offer = self._offer(
            package_text_raw="750 g",
            raw_payload={"description": "500 g"},
        )
        self.assertEqual(offer.package_signature(), ("750", "g", 1))
        self.assertEqual(offer.package_evidence_source, "package_text_raw")

    def test_image_filename_precedes_description(self):
        offer = self._offer(
            source_image_url="https://offer-images.api.edeka/item_400g_123.png",
            raw_payload={"description": "500 g"},
        )
        self.assertEqual(offer.package_signature(), ("400", "g", 1))
        self.assertEqual(offer.package_evidence_source, "source_image_filename")

    def test_non_edeka_does_not_use_description_fallback(self):
        offer = self._offer(
            source_chain="lidl",
            raw_payload={"description": "500 g"},
        )
        self.assertEqual(offer.package_signature(), (None, None, None))
        self.assertIsNone(offer.package_parse_method)

    def test_missing_description_stays_unknown(self):
        package = parse_edeka_description_package({"description": None})
        self.assertEqual(package.signature(), (None, None, None))
        self.assertIsNone(package.parse_method)
