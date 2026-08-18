from __future__ import annotations

import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import aldi_new_baseline_weekly_shadow_producer as producer
import aldi_visual_card_bridge_diagnostic_v2 as diagnostic


class AldiPlaywrightSharedMemoryPolicyTest(unittest.TestCase):
    def test_aldi_playwright_uses_native_dev_shm_pool(self) -> None:
        producer_source = inspect.getsource(producer.build_capture)
        diagnostic_source = inspect.getsource(diagnostic.run_diagnostic)

        for name, source in (
            ("producer", producer_source),
            ("diagnostic", diagnostic_source),
        ):
            with self.subTest(path=name):
                self.assertNotIn("--disable-dev-shm-usage", source)
                self.assertIn('args=["--disable-gpu"]', source)

    def test_shared_memory_fix_does_not_change_matching_contract(self) -> None:
        expected_selector = 'a[href][data-testid*="product-tile"]'
        self.assertEqual(producer.CANONICAL_PRODUCT_CARD_SELECTOR, expected_selector)
        self.assertEqual(diagnostic.CANONICAL_PRODUCT_CARD_SELECTOR, expected_selector)
        self.assertEqual(producer.MAX_VISUAL_CARDS, 512)
        self.assertEqual(diagnostic.MAX_CARDS, 512)
        self.assertEqual(
            producer.PARSER_CONTRACT,
            "aldi-new-baseline-objectid-source-productslug-href-html-stem-v02",
        )


if __name__ == "__main__":
    unittest.main()
