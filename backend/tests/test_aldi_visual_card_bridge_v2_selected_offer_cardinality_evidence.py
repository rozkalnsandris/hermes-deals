from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "aldi-visual-card-bridge-v2-dispatcher.sh"
sys.path.insert(0, str(ROOT / "tools"))
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class AldiVisualCardBridgeV2SelectedOfferCardinalityEvidenceTest(unittest.TestCase):
    def test_selected_offer_cardinality_classifies_zero_in_range_and_overflow(self):
        self.assertEqual(
            diagnostic._selected_offer_cardinality_evidence(0),
            {"bound_state": "ZERO", "max_offers": 512, "selected_offer_count": 0},
        )
        for count in (1, 263, 512):
            self.assertEqual(
                diagnostic._selected_offer_cardinality_evidence(count),
                {"bound_state": "IN_RANGE", "max_offers": 512, "selected_offer_count": count},
            )
        self.assertEqual(
            diagnostic._selected_offer_cardinality_evidence(513),
            {"bound_state": "OVERFLOW", "max_offers": 512, "selected_offer_count": 513},
        )

    def test_offer_bound_aligns_with_existing_card_domain(self):
        self.assertEqual(diagnostic.MAX_OFFERS, 512)
        self.assertEqual(diagnostic.MAX_OFFERS, diagnostic.MAX_CARDS)
        source = inspect.getsource(diagnostic._selected_offer_cardinality_evidence)
        self.assertIn("MAX_OFFERS", source)
        self.assertNotIn("MAX_OFFERS =", source)

    def test_blocked_run_emits_only_bounded_selected_offer_evidence_then_fails(self):
        source = inspect.getsource(diagnostic.run_diagnostic)
        self.assertIn('"SELECTED_OFFER_CARDINALITY_EVIDENCE="', source)
        self.assertIn('raise DiagnosticError("selected offer count outside diagnostic bound")', source)
        self.assertIn('selected_cardinality["bound_state"] != "IN_RANGE"', source)
        self.assertNotIn("selected_cardinality[\"bound_state\"] == \"IN_RANGE\"", source)

    def test_evidence_schema_contains_no_offer_content(self):
        evidence = diagnostic._selected_offer_cardinality_evidence(513)
        self.assertEqual(
            set(evidence),
            {"bound_state", "max_offers", "selected_offer_count"},
        )
        for forbidden in (
            "title", "brand", "price", "href", "url", "object_id", "token", "text", "html",
        ):
            self.assertFalse(any(forbidden in key.lower() for key in evidence))

    def test_existing_dispatcher_preserves_diagnostic_log_on_failure(self):
        source = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn('diagnostic_log="$staging/diagnostic.log"', source)
        self.assertIn('--output "$result" >"$diagnostic_log" 2>&1', source)
        self.assertIn('cat "$diagnostic_log"', source)
        self.assertIn('fail "v2 diagnostic blocked: exit=$diagnostic_rc"', source)

    def test_card_and_matching_contracts_remain_unchanged(self):
        self.assertEqual(diagnostic.MAX_CARDS, 512)
        self.assertEqual(
            diagnostic.CARD_SELECTOR,
            (
                'a[href][data-testid*="product-tile"],'
                'a[href][data-testid*="offer-tile"],'
                '[role="link"][data-testid*="product-tile"],'
                '[role="link"][data-testid*="offer-tile"]'
            ),
        )
        inventory_source = inspect.getsource(diagnostic._inventory)
        self.assertNotIn("textContent", inventory_source)
        self.assertNotIn("innerText", inventory_source)
        self.assertNotIn("raw.includes(token.value)", inventory_source)


if __name__ == "__main__":
    unittest.main()
