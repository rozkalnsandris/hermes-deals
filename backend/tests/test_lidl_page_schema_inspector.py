from __future__ import annotations

import unittest

from app.lidl_page_schema_inspector import analyze_page, grocery_hits, price_like_tokens


class LidlPageSchemaInspectorTest(unittest.TestCase):
    def test_price_like_tokens_cover_flyer_formats(self) -> None:
        tokens = price_like_tokens("Milch 1,29 € Butter 1.99€ Aktion 2,- Cola ,99 € Saft 89 ct")
        self.assertIn("1,29 €", tokens)
        self.assertIn("1.99€", tokens)
        self.assertIn("2,-", tokens)
        self.assertIn(",99 €", tokens)
        self.assertIn("89 ct", tokens)

    def test_grocery_terms_are_deduplicated(self) -> None:
        self.assertEqual(grocery_hits("Milch Milch Paprika Kaffee"), ["kaffee", "milch", "paprika"])


    def test_grocery_terms_do_not_match_inside_unrelated_words(self) -> None:
        self.assertEqual(grocery_hits("Preis Frische-Sieger Mikrofaser"), [])
        self.assertEqual(grocery_hits("Reis Eis Preis"), ["eis", "reis"])

    def test_analyze_page_finds_nested_product_price(self) -> None:
        page = {
            "number": 2,
            "keyWords": "Rote Paprika Aktion",
            "image": "https://example.test/page.jpg",
            "links": [
                {"productDetails": {"productId": "123", "title": "Paprika", "price": "1.29"}}
            ],
        }
        result = analyze_page(page)
        self.assertEqual(result["links_with_product_details"], 1)
        self.assertIn("paprika", result["keywords_grocery_hits"])
        self.assertEqual(result["keywords_text"], "Rote Paprika Aktion")
        paths = [item["path"] for item in result["interesting_fields"]]
        self.assertTrue(any(path.endswith(".price") for path in paths))
        self.assertIn("1.29", result["all_scalar_price_tokens"])


if __name__ == "__main__":
    unittest.main()
