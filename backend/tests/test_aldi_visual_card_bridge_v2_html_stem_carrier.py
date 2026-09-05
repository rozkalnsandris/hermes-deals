from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class AldiVisualCardBridgeV2HtmlStemCarrierTest(unittest.TestCase):
    def test_product_slug_adds_separate_exact_html_stem_family(self):
        self.assertEqual(
            diagnostic._identity_tokens("productSlug", "bio-kaffee-500-g"),
            [
                {
                    "field_path": "productSlug",
                    "token_kind": "url_slug_segment_exact",
                    "value": "bio-kaffee-500-g",
                }
            ],
        )
        tokens = diagnostic._tokens_for_offer(
            {"productSlug": "bio-kaffee-500-g"}
        )
        self.assertEqual(
            [(token["token_kind"], token["value"]) for token in tokens],
            [
                ("url_slug_segment_exact", "bio-kaffee-500-g"),
                ("url_slug_html_stem_exact", "bio-kaffee-500-g"),
            ],
        )

    def test_html_stem_family_is_bounded_to_product_slug_without_html_suffix(self):
        other = diagnostic._tokens_for_offer(
            {"canonicalSlug": "bio-kaffee-500-g"}
        )
        self.assertEqual(
            [token["token_kind"] for token in other],
            ["url_slug_segment_exact"],
        )

        already_html = diagnostic._tokens_for_offer(
            {"productSlug": "bio-kaffee-500-g.html"}
        )
        self.assertEqual(
            [token["token_kind"] for token in already_html],
            ["url_slug_segment_exact"],
        )

        source = inspect.getsource(diagnostic._tokens_for_offer)
        self.assertIn('path == "productSlug"', source)
        self.assertIn('len(identity_tokens[0]["value"]) <= 175', source)
        self.assertIn('.lower().endswith(".html")', source)

    def test_html_stem_carrier_is_exact_terminal_html_path_normalization_only(self):
        source = inspect.getsource(diagnostic._inventory)
        self.assertIn(
            "token.token_kind === 'url_slug_html_stem_exact' &&",
            source,
        )
        self.assertIn("parsed.segments.some(segment =>", source)
        self.assertIn("segment.endsWith('.html')", source)
        self.assertIn("segment.slice(0, -5) === token.value", source)
        self.assertIn(
            "kinds.add(`${name}:url_slug_html_stem_exact`)",
            source,
        )
        self.assertNotIn("segment.includes(token.value)", source)
        self.assertNotIn("parsed.path.includes(token.value)", source)
        self.assertNotIn("value.includes(token.value)", source)
        self.assertNotIn("endsWith('.htm')", source)
        self.assertIn(
            "name === 'href' || name === 'src' || name === 'action' ||",
            source,
        )
        self.assertIn("name === 'formaction' || name === 'poster'", source)
        self.assertNotIn("textContent", source)
        self.assertNotIn("innerText", source)
        self.assertNotIn("outerHTML", source)

    def test_exact_html_stem_family_can_pass_only_one_to_one(self):
        inventory = {
            "rows": [
                {
                    "object_id": "offer-a",
                    "tokens": [
                        {
                            "field_path": "productSlug",
                            "token_kind": "url_slug_html_stem_exact",
                            "card_keys": ["dom:card-a"],
                            "carrier_kinds": ["href:url_slug_html_stem_exact"],
                        }
                    ],
                },
                {
                    "object_id": "offer-b",
                    "tokens": [
                        {
                            "field_path": "productSlug",
                            "token_kind": "url_slug_html_stem_exact",
                            "card_keys": ["dom:card-b"],
                            "carrier_kinds": ["href:url_slug_html_stem_exact"],
                        }
                    ],
                },
            ]
        }
        families = diagnostic._family_summary(inventory, 2)
        self.assertEqual(len(families), 1)
        family = families[0]
        self.assertEqual(family["bridged_offer_count"], 2)
        self.assertEqual(family["missing_or_unmatched_offer_count"], 0)
        self.assertEqual(family["ambiguous_offer_count"], 0)
        self.assertEqual(family["card_collision_count"], 0)
        self.assertEqual(
            diagnostic._decision(families, 2),
            "EXACT_ONE_TO_ONE_BRIDGE_FOUND",
        )

        inventory["rows"][1]["tokens"][0]["card_keys"] = ["dom:card-a"]
        families = diagnostic._family_summary(inventory, 2)
        self.assertEqual(families[0]["card_collision_count"], 1)
        self.assertEqual(
            diagnostic._decision(families, 2),
            "PARTIAL_EXACT_BRIDGE_CANDIDATES",
        )

    def test_existing_card_selector_bounds_and_diagnostic_safety_stay_fixed(self):
        self.assertEqual(diagnostic.MAX_OFFERS, 512)
        self.assertEqual(diagnostic.MAX_CARDS, 512)
        self.assertEqual(
            diagnostic.CARD_SELECTOR,
            'a[href][data-testid*="product-tile"]',
        )
        run_source = inspect.getsource(diagnostic.run_diagnostic)
        for expected in (
            '"visible_text_matching_used": False',
            '"substring_matching_used": False',
            '"ocr_matching_used": False',
            '"producer_matching_contract_modified": False',
            '"request_created": False',
            '"request_accepted": False',
            '"production_database_write": False',
            '"review_publication_write": False',
            '"source_mutation": False',
            '"production_deploy": False',
            '"scheduler_activation": False',
            '"automatic_retry": False',
            '"production_canary": False',
        ):
            self.assertIn(expected, run_source)


if __name__ == "__main__":
    unittest.main()
