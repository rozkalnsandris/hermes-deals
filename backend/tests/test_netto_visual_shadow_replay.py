from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_visual_shadow_replay.py"
FIXTURE = Path(__file__).parent / "fixtures/netto/visual_cell_shadow_corpus_v1.json"
SPEC = importlib.util.spec_from_file_location("netto_visual_shadow_replay", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NettoVisualShadowReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = MODULE.load_corpus(FIXTURE)
        cls.report = MODULE.replay_shadow_corpus(cls.corpus)

    def row(self, index: int) -> dict[str, object]:
        return dict(zip(self.corpus["row_fields"], self.corpus["rows"][index], strict=True))

    def test_exact_corpus_binding(self) -> None:
        self.assertEqual((self.corpus["page_count"], self.corpus["cell_count"]), (17, 100))
        self.assertEqual(self.corpus["campaign_cell_counts"], {"hz31_hasb_4": 26, "hz32_hasb": 74})
        self.assertEqual(sorted(self.corpus["campaign_bindings"]), ["hz31_hasb_4", "hz32_hasb"])

    def test_exact_route_partition(self) -> None:
        self.assertEqual(self.report["route_counts"], {"automatic_candidate": 65, "review_required": 33, "excluded": 2})

    def test_first_pass_findings_preserved(self) -> None:
        self.assertEqual(self.corpus["first_pass_counts"], {
            "confirmed_title_defect_count": 32, "confirmed_price_defect_count": 4,
            "boundary_review_required_count": 10, "out_of_scope_cell_count": 2,
        })

    def test_second_review_and_promotion_blocked(self) -> None:
        self.assertEqual(self.report["second_review_status"], "pending")
        for key in ("promotion_ready", "automatic_approval_enabled", "automatic_publish_enabled", "database_write_performed", "deployment_performed", "production_apply_authorized"):
            self.assertFalse(self.report[key])
        self.assertTrue(self.report["review_only_default"])

    def test_review_truth_is_not_candidate_input(self) -> None:
        freixenet = self.row(57)
        self.assertEqual(freixenet["normal_price_candidates"], ["3.99"])
        self.assertEqual(freixenet["member_price_candidates"], ["3.79"])
        wrong = self.row(4)
        self.assertNotEqual(wrong["candidate_title"], wrong["expected_title"])
        self.assertIsNone(self.report["rows"][4]["selected_title"])

    def test_all_ten_mixed_boundaries_fail_closed(self) -> None:
        indexes = {self.row(i)["visual_index"] for i in range(100) if self.row(i)["boundary_conflict"]}
        self.assertEqual(len(indexes), 10)
        for result in self.report["rows"]:
            if result["visual_index"] in indexes:
                self.assertEqual(result["route"], "review_required")
                self.assertIsNone(result["selected_title"])
                self.assertIsNone(result["selected_normal_price"])

    def test_exactly_two_scope_exclusions(self) -> None:
        excluded = [row for row in self.report["rows"] if row["route"] == "excluded"]
        self.assertEqual([row["visual_index"] for row in excluded], [55, 78])

    def test_replay_is_deterministic(self) -> None:
        self.assertEqual(MODULE.replay_shadow_corpus(self.corpus), MODULE.replay_shadow_corpus(self.corpus))

    def test_missing_row_fails_closed(self) -> None:
        broken = json.loads(json.dumps(self.corpus)); broken["rows"].pop()
        with self.assertRaisesRegex(MODULE.ShadowReplayError, "100 rows"):
            MODULE.replay_shadow_corpus(broken)

    def test_duplicate_index_fails_closed(self) -> None:
        broken = json.loads(json.dumps(self.corpus)); pos = broken["row_fields"].index("visual_index")
        broken["rows"][1][pos] = broken["rows"][0][pos]
        with self.assertRaisesRegex(MODULE.ShadowReplayError, "unique"):
            MODULE.replay_shadow_corpus(broken)

    def test_unsafe_flag_fails_closed(self) -> None:
        broken = json.loads(json.dumps(self.corpus)); broken["safety"]["automatic_publish_enabled"] = True
        with self.assertRaisesRegex(MODULE.ShadowReplayError, "automatic_publish_enabled"):
            MODULE.replay_shadow_corpus(broken)


if __name__ == "__main__":
    unittest.main()
