from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class FakePage:
    def __init__(self, states):
        self.states = list(states)
        self.waits = []
        self.scripts = []

    def evaluate(self, script, arg):
        self.scripts.append(script)
        if not self.states:
            raise AssertionError("no fake state left")
        return self.states.pop(0)

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


class AldiVisualCardBridgeDiagnosticV2Test(unittest.TestCase):
    def test_identity_token_allowlist_excludes_semantic_and_objectid_fields(self):
        row = {
            "objectID": "1000083",
            "title": "Bananas 1 kg",
            "brand": "ALDI",
            "description": "semantic copy",
            "currentPrice": {"priceValue": 1.99},
            "productId": "P-12345",
            "canonicalUrl": "https://www.aldi-nord.de/angebote/foo-product-12345.html",
            "image": {"url": "https://www.aldi-nord.de/content/dam/aldi/foo_asset_34.jpg"},
        }
        tokens = diagnostic._tokens_for_offer(row)
        fields = {token["field_path"] for token in tokens}
        self.assertNotIn("objectID", fields)
        self.assertNotIn("title", fields)
        self.assertNotIn("brand", fields)
        self.assertNotIn("description", fields)
        self.assertFalse(any("price" in field.lower() for field in fields))
        self.assertIn("productId", fields)
        self.assertIn("canonicalUrl", fields)
        self.assertIn("image.url", fields)

    def test_numeric_value_only_allowed_for_strong_identity_field(self):
        self.assertEqual(diagnostic._identity_tokens("random.value", "123456"), [])
        tokens = diagnostic._identity_tokens("articleNumber", "123456")
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0]["token_kind"], "identity_exact")

    def test_url_tokens_are_exact_path_or_exact_segment_only(self):
        tokens = diagnostic._identity_tokens(
            "canonicalUrl",
            "https://www.aldi-nord.de/angebote/foo-product-12345.html?x=1",
        )
        kinds = {token["token_kind"] for token in tokens}
        self.assertIn("url_url_path_exact", kinds)
        self.assertIn("url_url_segment_exact", kinds)
        source = inspect.getsource(diagnostic._identity_tokens)
        self.assertNotIn("fuzzy", source.lower())

    def test_exact_one_to_one_bridge_decision_requires_full_coverage_and_no_collisions(self):
        families = [{
            "bridged_offer_count": 3,
            "missing_or_unmatched_offer_count": 0,
            "ambiguous_offer_count": 0,
            "card_collision_count": 0,
        }]
        self.assertEqual(
            diagnostic._decision(families, 3),
            "EXACT_ONE_TO_ONE_BRIDGE_FOUND",
        )

        families[0]["card_collision_count"] = 1
        self.assertEqual(
            diagnostic._decision(families, 3),
            "PARTIAL_EXACT_BRIDGE_CANDIDATES",
        )

    def test_family_summary_detects_collision(self):
        inventory = {
            "rows": [
                {
                    "object_id": "a",
                    "tokens": [{
                        "field_path": "productId",
                        "token_kind": "identity_exact",
                        "card_keys": ["card-1"],
                        "carrier_kinds": ["attribute_exact:data-product-id"],
                    }],
                },
                {
                    "object_id": "b",
                    "tokens": [{
                        "field_path": "productId",
                        "token_kind": "identity_exact",
                        "card_keys": ["card-1"],
                        "carrier_kinds": ["attribute_exact:data-product-id"],
                    }],
                },
            ]
        }
        families = diagnostic._family_summary(inventory, 2)
        self.assertEqual(families[0]["bridged_offer_count"], 2)
        self.assertEqual(families[0]["card_collision_count"], 1)
        self.assertEqual(
            diagnostic._decision(families, 2),
            "PARTIAL_EXACT_BRIDGE_CANDIDATES",
        )

    def test_family_summary_counts_missing_token_as_unmatched(self):
        inventory = {
            "rows": [
                {
                    "object_id": "a",
                    "tokens": [{
                        "field_path": "sku",
                        "token_kind": "identity_exact",
                        "card_keys": ["card-1"],
                        "carrier_kinds": ["attribute_exact:data-sku"],
                    }],
                },
                {"object_id": "b", "tokens": []},
            ]
        }
        family = diagnostic._family_summary(inventory, 2)[0]
        self.assertEqual(family["bridged_offer_count"], 1)
        self.assertEqual(family["missing_or_unmatched_offer_count"], 1)

    def test_card_stabilization_requires_four_identical_observations(self):
        page = FakePage([
            {"cards": 20, "height": 10000},
            {"cards": 24, "height": 12000},
            {"cards": 24, "height": 12000},
            {"cards": 24, "height": 12000},
            {"cards": 24, "height": 12000},
        ])
        result = diagnostic._stabilize_cards(page)
        self.assertEqual(result["visible_product_card_count"], 24)
        self.assertEqual(result["document_height"], 12000)
        self.assertEqual(len(page.waits), 4)

    def test_inventory_uses_dom_path_not_testid_as_card_identity(self):
        source = inspect.getsource(diagnostic._inventory)
        self.assertNotIn("if (testid) return", source)
        self.assertIn("return `dom:${parts.reverse().join('/')}`", source)
        self.assertIn("getAttribute('data-testid')", source)

    def test_testid_pattern_sanitizer_exports_hash_not_pattern_text(self):
        rows = diagnostic._sanitize_patterns({"product-tile-secret-slug-#": 3})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 3)
        self.assertEqual(rows[0]["pattern_length"], len("product-tile-secret-slug-#"))
        self.assertRegex(rows[0]["pattern_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("pattern", rows[0])

    def test_inventory_explicitly_excludes_non_card_script_style_template_and_text_matching(self):
        source = inspect.getsource(diagnostic._inventory)
        for tag in ("SCRIPT", "STYLE", "TEMPLATE", "NOSCRIPT", "SVG", "PATH"):
            self.assertIn(tag, source)
        self.assertNotIn("textContent", source)
        self.assertNotIn("innerText", source)
        self.assertNotIn("value.includes(token.value)", source)
        self.assertNotIn("raw.includes(token.value)", source)
        self.assertIn("parsed.segments.includes(token.value)", source)
        self.assertIn("parsed.queryValues.includes(token.value)", source)

    def test_run_result_safety_contract_forbids_semantic_fallbacks(self):
        source = inspect.getsource(diagnostic.run_diagnostic)
        for key in (
            '"raw_product_text_exported": False',
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
            self.assertIn(key, source)


if __name__ == "__main__":
    unittest.main()
