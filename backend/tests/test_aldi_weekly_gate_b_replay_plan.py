from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_weekly_gate_b_replay_plan.py"
RECEIPT = ROOT / "config" / "aldi-a30-rollover-reconciliation-receipt-31105044968.json"
SPEC = importlib.util.spec_from_file_location("aldi_weekly_gate_b_replay_plan", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AldiWeeklyGateBReplayPlanTest(unittest.TestCase):
    def receipt(self) -> dict[str, object]:
        return json.loads(RECEIPT.read_text(encoding="utf-8"))

    def semantic_report(self) -> tuple[dict[str, object], dict[int, dict[str, object]]]:
        receipt = self.receipt()
        classes = receipt["classifications"]
        moved = receipt["rollover"]["moved_pages"]
        current: dict[int, dict[str, object]] = {}
        for page in range(1, 42):
            digest = f"{page:064x}"[-64:]
            size = 12000 + page
            if page == 3:
                digest = classes["new_current_page_3"]["sha256"]
                size = classes["new_current_page_3"]["bytes"]
            elif page == 4:
                digest = moved[0]["sha256"]
            elif page == 5:
                digest = moved[1]["sha256"]
            elif page == 37:
                digest = moved[2]["sha256"]
            elif page == 41:
                digest = classes["information_page_41_change"]["new"]["sha256"]
                size = classes["information_page_41_change"]["new"]["bytes"]
            current[page] = {
                "page_number": page,
                "path": f"pages/current/page-{page:03d}.img",
                "sha256": digest,
                "bytes": size,
                "image_format": "jpeg",
            }

        non_positional = {3, 4, 5, 37, 41}
        comparisons = []
        for page in range(1, 42):
            right = current[page]["sha256"]
            left = right
            exact = page not in non_positional
            visual = exact
            if page == 3:
                left = moved[0]["sha256"]
            elif page == 4:
                left = moved[1]["sha256"]
            elif page == 5:
                left = moved[2]["sha256"]
            elif page == 37:
                left = classes["old_preview_page_37"]["sha256"]
            elif page == 41:
                left = classes["information_page_41_change"]["old"]["sha256"]
            comparisons.append(
                {
                    "page_number": page,
                    "left_sha256": left,
                    "right_sha256": right,
                    "exact_bytes": exact,
                    "visual_match": visual,
                }
            )
        report = {
            "rollover": {
                "comparisons": comparisons,
            },
        }
        return report, current

    def test_exact_merged_receipt_is_accepted(self) -> None:
        receipt = MODULE.load_receipt(RECEIPT)
        self.assertEqual(receipt["decision"], "shadow_reconciliation_accepted")
        self.assertEqual(receipt["artifact"]["run_id"], 31105044968)

    def test_build_plan_partitions_exact_41_page_cycle(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()

        plan = MODULE.build_plan(receipt, report, current)

        self.assertEqual(plan["decision"], "READY_FOR_SHADOW_REPLAY")
        self.assertEqual(
            plan["partition_counts"],
            {
                "carry_forward_parity": 39,
                "fresh_shadow_extraction": 1,
                "excluded_informational": 1,
            },
        )
        self.assertEqual(len(plan["current_page_manifest"]), 41)
        self.assertEqual(len(plan["carry_forward_mappings"]), 39)
        self.assertFalse(plan["candidate_parity_claimed"])
        self.assertFalse(plan["production_eligible"])
        self.assertFalse(plan["promotion_ready"])

    def test_exact_prior_plan_becomes_no_op(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()
        first = MODULE.build_plan(receipt, report, current)

        second = MODULE.build_plan(receipt, report, current, prior=first)

        self.assertEqual(second["decision"], "NO_OP")
        self.assertEqual(second["replay_fingerprint"], first["replay_fingerprint"])
        self.assertEqual(
            second["identity"]["current_manifest_sha256"],
            first["identity"]["current_manifest_sha256"],
        )

    def test_changed_offer_and_information_pages_never_carry_forward(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()

        plan = MODULE.build_plan(receipt, report, current)
        carry_new_pages = {
            row["new_current_page"] for row in plan["carry_forward_mappings"]
        }
        manifest = {row["page_number"]: row for row in plan["current_page_manifest"]}

        self.assertNotIn(3, carry_new_pages)
        self.assertNotIn(41, carry_new_pages)
        self.assertEqual(
            manifest[3]["disposition"],
            "fresh_shadow_extraction_required",
        )
        self.assertEqual(
            manifest[41]["disposition"],
            "non_offer_informational_excluded",
        )

    def test_removed_competition_page_is_not_carried_forward(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()

        plan = MODULE.build_plan(receipt, report, current)
        carry_old_pages = {
            row["old_preview_page"] for row in plan["carry_forward_mappings"]
        }

        self.assertNotIn(37, carry_old_pages)
        self.assertNotIn(41, carry_old_pages)
        self.assertEqual(
            {row["old_preview_page"] for row in plan["removed_old_preview_pages"]},
            {37, 41},
        )

    def test_swapped_moved_mapping_fails_closed(self) -> None:
        receipt = self.receipt()
        receipt["rollover"]["moved_pages"][0]["new_page"] = 5

        with self.assertRaisesRegex(MODULE.GateBError, "moved-page mapping mismatch"):
            MODULE.validate_receipt_contract(receipt)

    def test_non_exact_positional_page_fails_closed(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()
        report["rollover"]["comparisons"][0]["exact_bytes"] = False

        with self.assertRaisesRegex(MODULE.GateBError, "positional mapping not exact"):
            MODULE.build_plan(receipt, report, current)

    def test_unsafe_prior_plan_fails_closed(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()
        prior = MODULE.build_plan(receipt, report, current)
        prior["safety"]["candidate_creation_authorized"] = True

        with self.assertRaisesRegex(MODULE.GateBError, "prior plan safety mismatch"):
            MODULE.build_plan(receipt, report, current, prior=prior)

    def test_minimal_fingerprint_only_prior_fails_closed(self) -> None:
        minimal = {
            "schema_version": 1,
            "mode": MODULE.MODE,
            "issue_number": 200,
            "upstream_issue_numbers": [64, 165, 191, 196],
            "decision": "READY_FOR_SHADOW_REPLAY",
            "replay_fingerprint": "0" * 64,
            "partition_counts": {
                "carry_forward_parity": 39,
                "fresh_shadow_extraction": 1,
                "excluded_informational": 1,
            },
            "safety": MODULE.safety_contract(),
        }

        with self.assertRaisesRegex(MODULE.GateBError, "prior identity is incomplete"):
            MODULE.validate_prior_plan(minimal)

    def test_output_is_create_only_and_idempotent(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()
        plan = MODULE.build_plan(receipt, report, current)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate-b-plan.json"
            self.assertEqual(MODULE.write_plan(path, plan), "created")
            self.assertEqual(MODULE.write_plan(path, plan), "unchanged")
            changed = deepcopy(plan)
            changed["decision"] = "NO_OP"
            with self.assertRaisesRegex(MODULE.GateBError, "existing Gate B plan differs"):
                MODULE.write_plan(path, changed)

    def test_symlinked_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "evidence.json"
            link.symlink_to(target)

            with self.assertRaisesRegex(MODULE.GateBError, "symlinked evidence forbidden"):
                MODULE._safe_path(root, "evidence.json")

    def test_wrong_artifact_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.zip"
            path.write_bytes(b"not-the-authoritative-artifact")

            with self.assertRaisesRegex(MODULE.GateBError, "artifact ZIP SHA256 mismatch"):
                MODULE.verify_artifact_zip(path)

    def test_legacy_a31_is_reference_only(self) -> None:
        receipt = self.receipt()
        report, current = self.semantic_report()
        plan = MODULE.build_plan(receipt, report, current)

        reference = plan["legacy_a31_reference"]
        self.assertEqual(reference["page_counts"], {"current": 49, "preview": 41})
        self.assertEqual(reference["reuse_mode"], "frozen_reference_only")
        self.assertEqual(
            plan["next_step_scope"],
            "carry_forward_parity_plus_page_3_fresh_shadow_extraction",
        )


if __name__ == "__main__":
    unittest.main()
