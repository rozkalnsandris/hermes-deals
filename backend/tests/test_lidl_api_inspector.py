from __future__ import annotations

import unittest

from app.lidl_api_inspector import summarize_flyer_payload


class LidlApiInspectorTest(unittest.TestCase):
    def test_summarizes_wrapped_flyer_array_products(self) -> None:
        payload = {
            "flyer": {
                "id": "abc",
                "locale": "de-DE",
                "countryCode": "DE",
                "pages": [
                    {
                        "number": 1,
                        "keyWords": "MILCH 0,99 €",
                        "altText": "Milch Angebot",
                        "links": [],
                    }
                ],
                "products": [{"id": "p1", "name": "Milch", "price": "0.99"}],
                "relatedFlyers": [{"id": "r1"}],
            }
        }
        summary = summarize_flyer_payload(payload)
        self.assertTrue(summary["has_flyer"])
        self.assertEqual(summary["page_count"], 1)
        self.assertEqual(summary["product_collection_type"], "array")
        self.assertEqual(summary["product_count"], 1)
        self.assertEqual(summary["related_flyer_count"], 1)
        self.assertEqual(summary["flyer"]["countryCode"], "DE")
        self.assertEqual(summary["product_samples"][0]["price"], "0.99")
        self.assertIn("0,99", summary["page_samples"][0]["price_like_tokens"])

    def test_accepts_object_shaped_products(self) -> None:
        payload = {
            "flyer": {
                "id": "abc",
                "pages": [],
                "products": {
                    "internal-a": {"productId": "1001", "title": "Test Produkt", "price": "4.99"},
                    "internal-b": {"productId": "1002", "title": "Zweites Produkt", "price": "7.49"},
                },
            }
        }
        summary = summarize_flyer_payload(payload)
        self.assertEqual(summary["product_collection_type"], "object")
        self.assertEqual(summary["product_count"], 2)
        self.assertEqual(summary["product_samples"][0]["collection_key"], "internal-a")
        self.assertEqual(summary["product_samples"][0]["id"], "1001")

    def test_counts_product_details_inside_page_links(self) -> None:
        payload = {
            "flyer": {
                "pages": [
                    {
                        "number": 3,
                        "links": [
                            {
                                "icon": "link",
                                "productDetails": {
                                    "productId": "100347618",
                                    "title": "CRIVIT Pool",
                                    "brand": "CRIVIT",
                                    "price": "99.99",
                                },
                            },
                            {"icon": "external", "url": "https://example.invalid"},
                        ],
                    }
                ],
                "products": {},
            }
        }
        summary = summarize_flyer_payload(payload)
        self.assertEqual(summary["linked_product_detail_count"], 1)
        self.assertEqual(summary["linked_product_detail_unique_count"], 1)
        self.assertEqual(summary["page_samples"][0]["links_with_product_details"], 1)
        self.assertEqual(summary["linked_product_samples"][0]["price"], "99.99")

    def test_accepts_direct_flyer_shape(self) -> None:
        payload = {"id": "abc", "pages": [{"number": 1}], "products": {}}
        summary = summarize_flyer_payload(payload)
        self.assertTrue(summary["has_flyer"])
        self.assertEqual(summary["page_count"], 1)

    def test_rejects_non_flyer_payload(self) -> None:
        summary = summarize_flyer_payload({"error": "not found"})
        self.assertFalse(summary["has_flyer"])
        self.assertEqual(summary["page_count"], 0)
        self.assertIn("error", summary["top_level_keys"])


if __name__ == "__main__":
    unittest.main()
