from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class AldiVisualCardBridgeV2ExactCarrierContractTest(unittest.TestCase):
    def test_plain_structured_slug_is_an_exact_url_path_segment_token(self):
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
        for unsafe in (
            "bio/kaffee",
            "bio-kaffee?variant=1",
            "bio-kaffee#details",
            "bio kaffee",
        ):
            with self.subTest(value=unsafe):
                self.assertEqual(diagnostic._identity_tokens("productSlug", unsafe), [])

    def test_slug_carrier_is_only_an_exact_decoded_url_path_segment(self):
        source = inspect.getsource(diagnostic._inventory)
        self.assertIn(
            "token.token_kind === 'url_slug_segment_exact' &&\n"
            "                    parsed.segments.includes(token.value)",
            source,
        )
        self.assertIn("kinds.add(`${name}:url_slug_segment_exact`)", source)
        self.assertNotIn("token.token_kind === 'url_slug_exact'", source)
        self.assertNotIn("value.includes(token.value)", source)
        self.assertNotIn("parsed.path.includes(token.value)", source)
        self.assertNotIn("textContent", source)
        self.assertNotIn("innerText", source)
        self.assertNotIn("outerHTML", source)

    def test_slug_carrier_remains_limited_to_allowlisted_url_attributes(self):
        source = inspect.getsource(diagnostic._inventory)
        self.assertIn("name === 'href' || name === 'src' || name === 'action' ||", source)
        self.assertIn("name === 'formaction' || name === 'poster'", source)
        self.assertNotIn("url_slug_segment_exact' && value === token.value", source)
        self.assertNotIn("url_slug_segment_exact' && parsed.queryValues", source)
        self.assertIn("name === 'alt' || name === 'title' || name === 'aria-label' ||", source)

    def test_exact_one_to_one_slug_family_can_pass_only_without_ambiguity_or_collision(self):
        inventory = {
            "rows": [
                {
                    "object_id": "offer-a",
                    "tokens": [
                        {
                            "field_path": "productSlug",
                            "token_kind": "url_slug_segment_exact",
                            "card_keys": ["dom:card-a"],
                            "carrier_kinds": ["href:url_slug_segment_exact"],
                        }
                    ],
                },
                {
                    "object_id": "offer-b",
                    "tokens": [
                        {
                            "field_path": "productSlug",
                            "token_kind": "url_slug_segment_exact",
                            "card_keys": ["dom:card-b"],
                            "carrier_kinds": ["href:url_slug_segment_exact"],
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
        self.assertEqual(diagnostic._decision(families, 2), "EXACT_ONE_TO_ONE_BRIDGE_FOUND")

    def test_duplicate_card_carrier_stays_fail_closed(self):
        inventory = {
            "rows": [
                {
                    "object_id": object_id,
                    "tokens": [
                        {
                            "field_path": "productSlug",
                            "token_kind": "url_slug_segment_exact",
                            "card_keys": ["dom:shared-card"],
                            "carrier_kinds": ["href:url_slug_segment_exact"],
                        }
                    ],
                }
                for object_id in ("offer-a", "offer-b")
            ]
        }
        families = diagnostic._family_summary(inventory, 2)
        self.assertEqual(families[0]["card_collision_count"], 1)
        self.assertEqual(diagnostic._decision(families, 2), "PARTIAL_EXACT_BRIDGE_CANDIDATES")

    def test_multi_card_slug_carrier_stays_ambiguous(self):
        inventory = {
            "rows": [
                {
                    "object_id": "offer-a",
                    "tokens": [
                        {
                            "field_path": "productSlug",
                            "token_kind": "url_slug_segment_exact",
                            "card_keys": ["dom:card-a", "dom:card-b"],
                            "carrier_kinds": ["href:url_slug_segment_exact"],
                        }
                    ],
                }
            ]
        }
        families = diagnostic._family_summary(inventory, 1)
        self.assertEqual(families[0]["bridged_offer_count"], 0)
        self.assertEqual(families[0]["ambiguous_offer_count"], 1)
        self.assertEqual(diagnostic._decision(families, 1), "NO_EXACT_VISUAL_CARD_BRIDGE")

    def test_existing_cardinality_selector_and_url_token_contracts_stay_fixed(self):
        self.assertEqual(diagnostic.MAX_OFFERS, 512)
        self.assertEqual(diagnostic.MAX_CARDS, 512)
        self.assertEqual(
            diagnostic.CARD_SELECTOR,
            'a[href][data-testid*="product-tile"]',
        )
        tokens = diagnostic._url_tokens(
            "canonicalUrl",
            "https://www.aldi-nord.de/angebote/kaffee/bio-kaffee-500-g",
            "url",
        )
        kinds = {token["token_kind"] for token in tokens}
        self.assertIn("url_url_path_exact", kinds)
        self.assertIn("url_url_segment_exact", kinds)


if __name__ == "__main__":
    unittest.main()
