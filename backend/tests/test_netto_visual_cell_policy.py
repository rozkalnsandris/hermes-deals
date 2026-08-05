from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_visual_cell_policy.py"
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "netto"
    / "visual_cell_adversarial_v1.json"
)

SPEC = importlib.util.spec_from_file_location("netto_visual_cell_policy", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NettoVisualCellPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _input(self, case: dict[str, object]) -> dict[str, object]:
        campaign_id = str(case["campaign_id"])
        binding = self.fixture["campaign_bindings"][campaign_id]
        return {
            "campaign_id": campaign_id,
            "page_number": case["page_number"],
            "card_id": case["card_id"],
            "manifest_sha256": binding["manifest_sha256"],
            "pdf_sha256": binding["pdf_sha256"],
            "parser_identity": binding["parser_identity"],
            "store_external_id": self.fixture["store_external_id"],
            "scope": self.fixture["scope"],
            "candidate_title": case.get("candidate_title"),
            "normal_price_candidates": case.get(
                "normal_price_candidates", []
            ),
            "member_price_candidates": case.get(
                "member_price_candidates", []
            ),
            "product_scope": case.get("product_scope", "in_scope"),
            "boundary_conflict": case.get("boundary_conflict", False),
            "ownership_conflict": case.get("ownership_conflict", False),
            "title_ownership_conflict": case.get(
                "title_ownership_conflict", False
            ),
            "title_incomplete": case.get("title_incomplete", False),
            "offer_marker_count": case.get("offer_marker_count", 1),
        }

    def test_fixture_is_bound_to_exact_two_campaign_corpus(self) -> None:
        fixture = self.fixture
        self.assertEqual(fixture["store_external_id"], "5659")
        self.assertEqual(fixture["scope"], "family_primary_netto")
        self.assertEqual(
            sorted(fixture["campaign_bindings"]),
            ["hz31_hasb_4", "hz32_hasb"],
        )
        self.assertEqual(
            fixture["source_archive_sha256"],
            "882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2",
        )
        self.assertEqual(
            fixture["source_fixture_manifest_sha256"],
            "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147",
        )
        self.assertEqual(len(fixture["title_cases"]), 32)
        self.assertEqual(len(fixture["price_cases"]), 4)
        self.assertEqual(len(fixture["boundary_cases"]), 10)

    def test_all_confirmed_title_defects_fail_closed_without_inference(self) -> None:
        for case in self.fixture["title_cases"]:
            with self.subTest(case=case["case_id"]):
                decision = MODULE.evaluate_visual_cell(
                    self._input(case)
                )
                self.assertEqual(decision["route"], "review_required")
                self.assertEqual(
                    decision["field_routes"]["title"],
                    "review_required",
                )
                self.assertIsNone(decision["selected_title"])
                self.assertFalse(decision["promotion_ready"])
                self.assertFalse(decision["automatic_approval_enabled"])
                self.assertFalse(decision["automatic_publish_enabled"])
                self.assertFalse(decision["production_write_performed"])

    def test_mixed_boundaries_block_title_price_and_ownership(self) -> None:
        for case in self.fixture["boundary_cases"]:
            raw = self._input(case)
            raw.update(
                {
                    "boundary_conflict": True,
                    "ownership_conflict": True,
                    "offer_marker_count": 2,
                }
            )
            with self.subTest(case=case["case_id"]):
                decision = MODULE.evaluate_visual_cell(raw)
                self.assertEqual(decision["route"], "review_required")
                self.assertEqual(
                    decision["field_routes"]["card_ownership"],
                    "review_required",
                )
                self.assertEqual(
                    decision["field_routes"]["title"],
                    "review_required",
                )
                self.assertEqual(
                    decision["field_routes"]["price"],
                    "review_required",
                )
                self.assertIsNone(decision["selected_title"])
                self.assertIsNone(decision["selected_normal_price"])
                self.assertIn("mixed_card_boundary", decision["reasons"])
                self.assertIn("card_ownership_conflict", decision["reasons"])

    def test_normal_and_member_prices_remain_separate(self) -> None:
        by_id = {
            case["case_id"]: case
            for case in self.fixture["price_cases"]
        }
        freixenet = by_id["price-057"]
        decision = MODULE.evaluate_visual_cell(
            self._input(freixenet)
        )
        self.assertEqual(decision["route"], "automatic_candidate")
        self.assertEqual(decision["selected_normal_price"], "3.99")
        self.assertEqual(decision["selected_member_price"], "3.79")
        self.assertEqual(
            decision["field_routes"]["price"],
            "automatic_candidate",
        )
        self.assertFalse(decision["promotion_ready"])

    def test_ambiguous_mixed_prices_do_not_select_a_normal_price(self) -> None:
        for case in self.fixture["price_cases"]:
            if case["case_id"] == "price-057":
                continue
            with self.subTest(case=case["case_id"]):
                decision = MODULE.evaluate_visual_cell(
                    self._input(case)
                )
                self.assertEqual(decision["route"], "review_required")
                self.assertIsNone(decision["selected_normal_price"])
                self.assertEqual(
                    decision["field_routes"]["price"],
                    "review_required",
                )
                self.assertIn("ambiguous_normal_price", decision["reasons"])

    def test_member_price_cannot_substitute_for_missing_normal_price(self) -> None:
        raw = self._input(self.fixture["price_cases"][-1])
        raw["normal_price_candidates"] = []
        raw["member_price_candidates"] = ["3.79"]
        decision = MODULE.evaluate_visual_cell(raw)
        self.assertEqual(decision["route"], "review_required")
        self.assertIsNone(decision["selected_normal_price"])
        self.assertEqual(decision["selected_member_price"], "3.79")
        self.assertIn(
            "member_price_cannot_replace_normal_price",
            decision["reasons"],
        )

    def test_clean_generic_cell_is_only_a_candidate_not_promotion_ready(self) -> None:
        raw = self._input(self.fixture["price_cases"][-1])
        raw.update(
            {
                "campaign_id": "generic-campaign",
                "card_id": "generic-card",
                "candidate_title": "Generic Product",
                "normal_price_candidates": ["1.99"],
                "member_price_candidates": ["1.79"],
            }
        )
        decision = MODULE.evaluate_visual_cell(raw)
        self.assertEqual(decision["route"], "automatic_candidate")
        self.assertEqual(decision["selected_title"], "Generic Product")
        self.assertEqual(decision["selected_normal_price"], "1.99")
        self.assertEqual(decision["selected_member_price"], "1.79")
        self.assertEqual(
            decision["field_routes"]["brand"],
            "review_required",
        )
        self.assertEqual(
            decision["field_routes"]["package"],
            "review_required",
        )
        self.assertEqual(
            decision["field_routes"]["validity"],
            "review_required",
        )
        self.assertFalse(decision["promotion_ready"])

    def test_out_of_scope_cell_is_excluded(self) -> None:
        raw = self._input(self.fixture["price_cases"][-1])
        raw["product_scope"] = "out_of_scope"
        decision = MODULE.evaluate_visual_cell(raw)
        self.assertEqual(decision["route"], "excluded")
        self.assertIsNone(decision["selected_title"])
        self.assertIsNone(decision["selected_normal_price"])
        self.assertIsNone(decision["selected_member_price"])
        self.assertIn("product_out_of_scope", decision["reasons"])

    def test_decision_is_deterministic_and_price_order_independent(self) -> None:
        raw = self._input(self.fixture["price_cases"][-1])
        raw["normal_price_candidates"] = ["3.99", "3.99"]
        raw["member_price_candidates"] = ["3.79", "3.79"]
        forward = MODULE.evaluate_visual_cell(raw)
        raw["normal_price_candidates"] = list(
            reversed(raw["normal_price_candidates"])
        )
        raw["member_price_candidates"] = list(
            reversed(raw["member_price_candidates"])
        )
        reverse = MODULE.evaluate_visual_cell(raw)
        self.assertEqual(forward, reverse)

    def test_policy_has_no_campaign_or_product_specific_overrides(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        for campaign_id in self.fixture["campaign_bindings"]:
            self.assertNotIn(campaign_id, source)
        for case in self.fixture["title_cases"]:
            self.assertNotIn(case["visual_truth_title"], source)

    def test_invalid_provenance_fails_closed(self) -> None:
        raw = self._input(self.fixture["price_cases"][-1])
        raw["manifest_sha256"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "manifest_sha256"):
            MODULE.evaluate_visual_cell(raw)


if __name__ == "__main__":
    unittest.main()
