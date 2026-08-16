from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "aldi-visual-card-bridge-v2-dispatcher.sh"
sys.path.insert(0, str(ROOT / "tools"))
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class AldiVisualCardBridgeV2CardinalityEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DISPATCHER.read_text(encoding="utf-8")
        marker = "if grep -Fq 'ERROR=DiagnosticError:visible product-card count outside diagnostic bound'"
        start = cls.source.index(marker)
        end = cls.source.index('  fail "v2 diagnostic blocked: exit=$diagnostic_rc"', start)
        cls.probe = cls.source[start:end]

    def test_probe_runs_only_for_exact_cardinality_blocker(self):
        self.assertIn(
            "grep -Fq 'ERROR=DiagnosticError:visible product-card count outside diagnostic bound'",
            self.source,
        )
        self.assertIn('fail "v2 diagnostic blocked: exit=$diagnostic_rc"', self.source)
        self.assertNotIn("CARDINALITY_EVIDENCE=", self.source[: self.source.index("if [[ \"$diagnostic_rc\" -ne 0 ]]")])

    def test_probe_preserves_existing_card_bound(self):
        self.assertIn("diagnostic.MAX_CARDS", self.probe)
        self.assertNotIn("MAX_CARDS =", self.probe)
        self.assertIn('bound_state = "ZERO"', self.probe)
        self.assertIn('bound_state = "OVERFLOW"', self.probe)
        self.assertIn('bound_state = "IN_RANGE"', self.probe)
        self.assertIn('bound_state = "UNSTABLE"', self.probe)

    def test_probe_exports_only_count_and_structural_metadata(self):
        for key in (
            '"bound_state"',
            '"document_height"',
            '"max_cards"',
            '"selected_offer_count"',
            '"selector_family_counts"',
            '"stabilized"',
            '"structural_unique_card_count"',
            '"visible_combined_count"',
        ):
            self.assertIn(key, self.probe)
        self.assertIn('print("CARDINALITY_EVIDENCE=" + json.dumps(', self.probe)
        for forbidden in (
            "textContent",
            "innerText",
            "innerHTML",
            "outerHTML",
            "product_title",
            "token_value",
            "screenshot",
        ):
            self.assertNotIn(forbidden, self.probe)

    def test_probe_uses_fixed_selector_family_names(self):
        for name in (
            '"product_anchor"',
            '"offer_anchor"',
            '"product_role_link"',
            '"offer_role_link"',
        ):
            self.assertIn(name, self.probe)
        self.assertIn("structural_unique_card_count: structural.size", self.probe)
        self.assertIn("visible_combined_count: visibleCards.length", self.probe)

    def test_probe_selector_union_matches_v2_card_selector(self):
        expected = (
            'a[href][data-testid*="product-tile"],'
            'a[href][data-testid*="offer-tile"],'
            '[role="link"][data-testid*="product-tile"],'
            '[role="link"][data-testid*="offer-tile"]'
        )
        self.assertEqual(diagnostic.CARD_SELECTOR, expected)
        for selector in expected.split(","):
            self.assertIn(selector, self.probe)

    def test_probe_remains_read_only_and_fail_closed(self):
        self.assertIn('source_url = "https://www.aldi-nord.de/angebote.html"', self.probe)
        self.assertIn("page.goto(source_url", self.probe)
        self.assertNotIn("page.screenshot", self.probe)
        self.assertNotIn("write_text", self.probe)
        self.assertNotIn("open(\"", self.probe)
        self.assertNotIn("request_created", self.probe)
        self.assertNotIn("production_database", self.probe)
        self.assertIn('fail "v2 diagnostic blocked: exit=$diagnostic_rc"', self.source)


if __name__ == "__main__":
    unittest.main()
