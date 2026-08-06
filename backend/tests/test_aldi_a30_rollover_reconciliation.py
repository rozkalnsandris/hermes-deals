from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_a30_rollover_reconciliation.py"
RECEIPT = ROOT / "config" / "aldi-a30-rollover-reconciliation-receipt-31105044968.json"
SPEC = importlib.util.spec_from_file_location("aldi_a30_rollover_reconciliation", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AldiA30RolloverReconciliationTest(unittest.TestCase):
    def receipt(self) -> dict[str, object]:
        return json.loads(RECEIPT.read_text(encoding="utf-8"))

    def semantic_evidence(self) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        receipt = self.receipt()
        classes = receipt["classifications"]
        evidence = receipt["evidence"]
        rollover = receipt["rollover"]

        current_rows = []
        preview_rows = []
        for page in range(1, 42):
            current_sha = f"{page:064x}"[-64:]
            current_bytes = 12000 + page
            if page == 3:
                current_sha = classes["new_current_page_3"]["sha256"]
                current_bytes = classes["new_current_page_3"]["bytes"]
            elif page == 4:
                current_sha = rollover["moved_pages"][0]["sha256"]
            elif page == 5:
                current_sha = rollover["moved_pages"][1]["sha256"]
            elif page == 37:
                current_sha = rollover["moved_pages"][2]["sha256"]
            elif page == 41:
                current_sha = classes["information_page_41_change"]["new"]["sha256"]
                current_bytes = classes["information_page_41_change"]["new"]["bytes"]
            current_rows.append(
                {
                    "page_number": page,
                    "path": f"pages/current/page-{page:03d}.img",
                    "sha256": current_sha,
                    "bytes": current_bytes,
                }
            )
            preview_rows.append(
                {
                    "page_number": page,
                    "path": f"pages/preview/page-{page:03d}.img",
                    "sha256": f"{page + 100:064x}"[-64:],
                    "bytes": 13000 + page,
                }
            )

        report = {
            "schema_version": 2,
            "mode": "ALDI_A30_AUTHORITATIVE_CYCLE_ACQUISITION_V01",
            "commit_sha": receipt["artifact"]["registered_commit"],
            "result": "blocked",
            "state": "authoritative_cycle_blocked",
            "source_roots_distinct": True,
            "production_database_write": False,
            "production_deployment": False,
            "collector_executed": False,
            "automatic_approval": False,
            "automatic_publication": False,
            "sources": {
                "current": {"page_count": 41, "pages": current_rows},
                "preview": {"page_count": 41, "pages": preview_rows},
            },
            "rollover": {
                "required_pages": 41,
                "matched_pages": 36,
                "all_pages_match": False,
            },
            "rollover_analysis": {
                "schema_version": 1,
                "mode": "ALDI_A30_ROLLOVER_REVIEW_ANALYSIS_V01",
                "positional_visual_matched_pages": 36,
                "exact_positional_matched_pages": 36,
                "content_set_matched_pages": 39,
                "moved_pages": deepcopy(rollover["moved_pages"]),
                "old_only_pages": [37, 41],
                "new_only_pages": [3, 41],
                "duplicate_content_groups": [],
                "manual_review_required": True,
                "strict_41_of_41_gate_unchanged": True,
                "automatic_promotion_allowed": False,
            },
        }

        old37 = classes["old_preview_page_37"]
        old41 = classes["information_page_41_change"]["old"]
        new3 = classes["new_current_page_3"]
        new41 = classes["information_page_41_change"]["new"]
        manual = {
            "schema_version": 1,
            "mode": "ALDI_A30_ROLLOVER_REVIEW_ANALYSIS_V01",
            "classification": "manual_review_required",
            "exact_positional_matched_pages": 36,
            "content_set_matched_pages": 39,
            "moved_pages": deepcopy(rollover["moved_pages"]),
            "old_only_pages": [37, 41],
            "new_only_pages": [3, 41],
            "duplicate_content_groups": [],
            "automatic_promotion_allowed": False,
            "old_preview_files": [
                {
                    "label": "old_preview",
                    "page_number": 37,
                    "path": old37["path"].removeprefix("evidence/"),
                    "sha256": old37["sha256"],
                    "bytes": old37["bytes"],
                },
                {
                    "label": "old_preview",
                    "page_number": 41,
                    "path": old41["path"].removeprefix("evidence/"),
                    "sha256": old41["sha256"],
                    "bytes": old41["bytes"],
                },
            ],
            "new_current_files": [
                {
                    "label": "new_current",
                    "page_number": 3,
                    "path": new3["path"].removeprefix("evidence/"),
                    "sha256": new3["sha256"],
                    "bytes": new3["bytes"],
                },
                {
                    "label": "new_current",
                    "page_number": 41,
                    "path": new41["path"].removeprefix("evidence/"),
                    "sha256": new41["sha256"],
                    "bytes": new41["bytes"],
                },
            ],
        }

        manifest_rows = []
        for key in ("authoritative_report", "manual_review"):
            descriptor = evidence[key]
            manifest_rows.append(
                {
                    "path": descriptor["path"],
                    "sha256": descriptor["sha256"],
                    "bytes": descriptor["bytes"],
                }
            )
        for descriptor in (new3, old37, old41, new41):
            manifest_rows.append(
                {
                    "path": descriptor["path"],
                    "sha256": descriptor["sha256"],
                    "bytes": descriptor["bytes"],
                }
            )
        manifest = {
            "schema_version": 1,
            "audit": "aldi-a30-authoritative-cycle",
            "audit_exit_code": 3,
            "commit_sha": receipt["artifact"]["registered_commit"],
            "sanitization_passed": True,
            "production_apply_authorized": False,
            "files": manifest_rows,
        }
        return manifest, report, manual

    def test_exact_authoritative_receipt_is_accepted(self) -> None:
        receipt = MODULE.load_authoritative_receipt(RECEIPT)
        self.assertEqual(receipt["decision"], "shadow_reconciliation_accepted")
        self.assertEqual(receipt["artifact"]["run_id"], 31105044968)

    def test_semantic_reconciliation_accepts_only_shadow_next_step(self) -> None:
        receipt = self.receipt()
        manifest, report, manual = self.semantic_evidence()
        result = MODULE.validate_evidence_semantics(receipt, manifest, report, manual)
        self.assertEqual(result["decision"], "shadow_reconciliation_accepted")
        self.assertEqual(result["content_set_matched_pages"], 39)
        self.assertEqual(result["moved_page_count"], 3)
        self.assertTrue(result["strict_41_of_41_gate_unchanged"])
        self.assertFalse(result["automatic_promotion_allowed"])
        self.assertFalse(result["production_database_write"])
        self.assertEqual(result["next_step_scope"], "shadow_parser_and_parity_only")

    def test_swapped_moved_pages_fail_closed(self) -> None:
        receipt = self.receipt()
        receipt["rollover"]["moved_pages"][0]["new_page"] = 5
        with self.assertRaisesRegex(MODULE.ReconciliationError, "moved-page mapping mismatch"):
            MODULE.validate_receipt_contract(receipt)

    def test_weakened_page_classification_fails_closed(self) -> None:
        receipt = self.receipt()
        receipt["classifications"]["old_preview_page_37"]["classification"] = "unknown"
        with self.assertRaisesRegex(MODULE.ReconciliationError, "classification weakened"):
            MODULE.validate_receipt_contract(receipt)

    def test_missing_page_evidence_fails_closed(self) -> None:
        receipt = self.receipt()
        manifest, report, manual = self.semantic_evidence()
        missing = receipt["classifications"]["new_current_page_3"]["path"]
        manifest["files"] = [row for row in manifest["files"] if row["path"] != missing]
        with self.assertRaisesRegex(MODULE.ReconciliationError, "manifest evidence missing"):
            MODULE.validate_evidence_semantics(receipt, manifest, report, manual)

    def test_attempted_automatic_promotion_fails_closed(self) -> None:
        receipt = self.receipt()
        receipt["safety"]["automatic_promotion_allowed"] = True
        with self.assertRaisesRegex(MODULE.ReconciliationError, "unsafe receipt flag"):
            MODULE.validate_receipt_contract(receipt)

    def test_page_count_drift_fails_closed(self) -> None:
        receipt = self.receipt()
        manifest, report, manual = self.semantic_evidence()
        report["sources"]["current"]["page_count"] = 40
        with self.assertRaisesRegex(MODULE.ReconciliationError, "current page count mismatch"):
            MODULE.validate_evidence_semantics(receipt, manifest, report, manual)

    def test_actual_file_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "evidence.json"
            path.write_text("{}\n", encoding="utf-8")
            descriptor = {
                "path": "evidence.json",
                "bytes": path.stat().st_size,
                "sha256": "0" * 64,
            }
            with self.assertRaisesRegex(MODULE.ReconciliationError, "SHA256 mismatch"):
                MODULE._verify_file(root, descriptor)


if __name__ == "__main__":
    unittest.main()
