from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "aldi-visual-card-bridge-v2-dispatcher.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-aldi-visual-card-bridge-v2.yml"
sys.path.insert(0, str(ROOT / "tools"))
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class AldiVisualCardBridgeV2DispatcherOfferBoundAlignmentTest(unittest.TestCase):
    def test_dispatcher_and_workflow_follow_diagnostic_bounds(self):
        expected = (
            f"if not 0 < selected <= {diagnostic.MAX_OFFERS} "
            f"or not 0 < cards <= {diagnostic.MAX_CARDS}:"
        )
        dispatcher = DISPATCHER.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(diagnostic.MAX_OFFERS, 512)
        self.assertEqual(diagnostic.MAX_CARDS, 512)
        self.assertIn(expected, dispatcher)
        self.assertIn(expected, workflow)
        self.assertNotIn("selected <= 256", dispatcher)
        self.assertNotIn("selected <= 256", workflow)


if __name__ == "__main__":
    unittest.main()
