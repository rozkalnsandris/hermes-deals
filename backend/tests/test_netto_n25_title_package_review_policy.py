from __future__ import annotations

import json
from pathlib import Path
import unittest


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "netto"
    / "n25_title_package_review_policy_v1.json"
)


class NettoN25TitlePackageReviewPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_policy_is_bound_to_n24_truth(self) -> None:
        basis = self.policy["basis"]
        self.assertEqual(
            basis["n24_visual_truth_fixture_sha256"],
            "b81c5733a10ce574d927f00697371edf1277da6566c0e223264497ff8c427dd0",
        )
        self.assertEqual(basis["evaluated_true_prediction_count"], 61)
        self.assertEqual(basis["combined_full_title_count"], 46)
        self.assertEqual(basis["combined_full_title_rate"], 0.754098)
        self.assertEqual(basis["automatic_package_selection_count"], 0)

    def test_title_must_remain_review_only(self) -> None:
        title = self.policy["title_policy"]
        self.assertFalse(title["automatic_selection_enabled"])
        self.assertTrue(title["selected_title_must_be_null"])
        self.assertTrue(title["candidate_evidence_allowed"])
        self.assertEqual(title["route"], "review_required")
        self.assertLess(
            self.policy["basis"]["combined_full_title_rate"],
            self.policy["thresholds"]["automatic_title_full_coverage_minimum"],
        )

    def test_package_must_remain_review_only(self) -> None:
        package = self.policy["package_policy"]
        self.assertFalse(package["automatic_selection_enabled"])
        self.assertTrue(package["selected_package_must_be_null"])
        self.assertTrue(package["candidate_evidence_allowed"])
        self.assertEqual(package["route"], "review_required")
        self.assertLess(
            self.policy["basis"]["automatic_package_selection_count"] / 61,
            self.policy["thresholds"]["automatic_package_selection_minimum"],
        )

    def test_card_price_pass_does_not_allow_publish(self) -> None:
        card = self.policy["card_and_normal_price_policy"]
        self.assertEqual(card["blind_gate"], "pass")
        self.assertFalse(card["automatic_publish_enabled"])

    def test_overall_promotion_remains_blocked(self) -> None:
        promotion = self.policy["promotion_policy"]
        self.assertEqual(promotion["overall_promotion"], "blocked")
        self.assertFalse(promotion["production_integration_allowed"])
        self.assertFalse(promotion["automatic_approval_enabled"])
        self.assertFalse(promotion["automatic_publish_enabled"])
        self.assertIn(
            "new Dortmund store 5659 weekly canary",
            promotion["required_next_gates"],
        )

    def test_no_write_is_recorded(self) -> None:
        self.assertFalse(self.policy["production_write_performed"])


if __name__ == "__main__":
    unittest.main()
