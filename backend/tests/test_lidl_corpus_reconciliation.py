from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.lidl_corpus_reconciliation import (
    load_reconciliation_plan,
    semantic_digest,
    semantic_material_from_row,
    validate_import_approval,
)


class LidlCorpusReconciliationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.flyer_key = "20260803-20260808-r21-c20598d30ff5"
        self.scan = "v631-7191e910f07b"
        self.raw_sha = "e" * 64
        self.pdf_sha = "c" * 64
        self.parser_sha = "7" * 64
        self.rows = []
        entries = []
        manual_ids = [f"manual-review-{index:032x}" for index in range(54)]
        for ordinal in range(1, 205):
            row = {
                "page": str((ordinal % 69) + 1),
                "product_name": f"TEST Product {ordinal}",
                "package_text": "500 g",
                "price_eur": f"{1 + ordinal / 100:.2f}",
                "regular_price_eur": "",
                "app_price_eur": "",
                "valid_from": "2026-08-03",
                "valid_until": "2026-08-08",
            }
            self.rows.append(row)
            material = semantic_material_from_row(row)
            digest = semantic_digest(material)
            if ordinal <= 134:
                source_id = f"lidl:corpus:{self.flyer_key}:scan-0003:r{ordinal:03d}:{digest[:12]}"
                origin = "reused_exact_previous_corpus_identity"
                previous_offer_id = f"00000000-0000-0000-0000-{ordinal:012d}"
                previous_snapshot_id = "7fc04436-ad76-58ab-ab73-5bc7f6de7bbf"
            else:
                source_id = f"lidl:flyer:{self.flyer_key}:semantic-v2:{digest[:24]}"
                origin = "new_semantic_v2_identity"
                previous_offer_id = None
                previous_snapshot_id = None
            entries.append(
                {
                    "ordinal": ordinal,
                    "source_offer_id": source_id,
                    "identity_origin": origin,
                    "previous_offer_candidate_id": previous_offer_id,
                    "previous_snapshot_id": previous_snapshot_id,
                    "semantic_digest_sha256": digest,
                    "semantic_material": material,
                }
            )
        self.plan = {
            "schema_version": 1,
            "workflow_version": "lidl-corpus-source-id-reconciliation-v1",
            "decision": "reuse_exact_previous_corpus_ids_and_allocate_semantic_v2_for_new_rows",
            "flyer_key": self.flyer_key,
            "scan": self.scan,
            "source": {"raw_sha256": self.raw_sha, "pdf_sha256": self.pdf_sha},
            "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
            "parser_sha256": self.parser_sha,
            "previous_corpus_snapshot": {
                "snapshot_id": "7fc04436-ad76-58ab-ab73-5bc7f6de7bbf",
                "raw_sha256": "a54d233f9ea5a44bf80655572d0c5d76797cb7fbf07842eeb7aabdacce9218d0",
                "rows": 134,
            },
            "protected_manual_publications": {
                "database_rows": 58,
                "distinct_source_offer_ids": 54,
                "revision_rows_collapsed_by_source_offer_id": 4,
                "source_offer_ids": manual_ids,
            },
            "counts": {
                "planned_safe_rows": 204,
                "reused_exact_previous_corpus_ids": 134,
                "new_semantic_v2_ids": 70,
                "identity_collisions": 0,
                "manual_identity_collisions": 0,
            },
            "permissions": {
                "db_write": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "timer_install": False,
            },
            "entries": entries,
        }
        self.plan_path, self.plan_sha = self._write("plan.json", self.plan)
        self.approval = {
            "schema_version": 1,
            "workflow_version": "lidl-controlled-safe-import-approval-v2-read-dedup",
            "decision": "approve_reconciled_safe_import",
            "flyer_key": self.flyer_key,
            "scan": self.scan,
            "source": {"raw_sha256": self.raw_sha, "pdf_sha256": self.pdf_sha},
            "identity_plan_sha256": self.plan_sha,
            "counts": {
                "new_source_snapshots": 1,
                "safe_offer_candidates": 204,
                "reused_previous_source_offer_ids": 134,
                "new_semantic_v2_source_offer_ids": 70,
                "protected_manual_database_rows": 58,
                "protected_manual_distinct_source_offer_ids": 54,
                "database_target_distinct_source_offer_ids": 258,

                "expected_visible_target_flyer_rows": 257,

                "completeness_rescue_precedence_suppressions": 1,
            },
            "permissions": {
                "db_write": True,
                "source_snapshot_write": True,
                "offer_candidate_write": True,
                "delete_existing_rows": False,
                "update_existing_rows": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "timer_install": False,
            },
        }
        self.approval_path, self.approval_sha = self._write(
            "approval.json", self.approval
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, payload: dict):
        path = self.root / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        import hashlib

        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def _load_plan(self):
        return load_reconciliation_plan(
            path=self.plan_path,
            expected_sha256=self.plan_sha,
            flyer_key=self.flyer_key,
            scan_name=self.scan,
            parser_version="lidl-pdf-v08c-r61-shadow-v631",
            parser_sha256=self.parser_sha,
            raw_sha256=self.raw_sha,
            pdf_sha256=self.pdf_sha,
            safe_rows=self.rows,
        )

    def test_exact_reconciliation_plan_is_accepted(self) -> None:
        plan = self._load_plan()
        self.assertEqual(len(plan.entries), 204)
        self.assertEqual(plan.sha256, self.plan_sha)

    def test_reconciliation_plan_sha_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON SHA mismatch"):
            load_reconciliation_plan(
                path=self.plan_path,
                expected_sha256="0" * 64,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                parser_version="lidl-pdf-v08c-r61-shadow-v631",
                parser_sha256=self.parser_sha,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                safe_rows=self.rows,
            )

    def test_semantic_row_drift_is_rejected(self) -> None:
        rows = [dict(row) for row in self.rows]
        rows[0]["price_eur"] = "99.99"
        with self.assertRaisesRegex(ValueError, "semantic material mismatch"):
            load_reconciliation_plan(
                path=self.plan_path,
                expected_sha256=self.plan_sha,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                parser_version="lidl-pdf-v08c-r61-shadow-v631",
                parser_sha256=self.parser_sha,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                safe_rows=rows,
            )

    def test_unsafe_identity_plan_permissions_are_rejected(self) -> None:
        payload = json.loads(json.dumps(self.plan))
        payload["permissions"]["db_write"] = True
        path, sha = self._write("unsafe-plan.json", payload)
        with self.assertRaisesRegex(ValueError, "unsafe permissions"):
            load_reconciliation_plan(
                path=path,
                expected_sha256=sha,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                parser_version="lidl-pdf-v08c-r61-shadow-v631",
                parser_sha256=self.parser_sha,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                safe_rows=self.rows,
            )

    def test_manual_identity_collision_is_rejected(self) -> None:
        payload = json.loads(json.dumps(self.plan))
        payload["protected_manual_publications"]["source_offer_ids"][0] = payload[
            "entries"
        ][0]["source_offer_id"]
        path, sha = self._write("collision-plan.json", payload)
        with self.assertRaisesRegex(ValueError, "manual publications"):
            load_reconciliation_plan(
                path=path,
                expected_sha256=sha,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                parser_version="lidl-pdf-v08c-r61-shadow-v631",
                parser_sha256=self.parser_sha,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                safe_rows=self.rows,
            )

    def test_exact_safe_import_approval_is_accepted(self) -> None:
        payload = validate_import_approval(
            path=self.approval_path,
            expected_sha256=self.approval_sha,
            flyer_key=self.flyer_key,
            scan_name=self.scan,
            raw_sha256=self.raw_sha,
            pdf_sha256=self.pdf_sha,
            identity_plan_sha256=self.plan_sha,
        )
        self.assertTrue(payload["permissions"]["db_write"])
        self.assertFalse(payload["permissions"]["review_seed"])

    def test_safe_import_approval_binds_read_dedup_counts(self) -> None:
        payload = json.loads(self.approval_path.read_text(encoding="utf-8"))
        payload["counts"]["expected_visible_target_flyer_rows"] = 258
        path, sha = self._write("bad-visible-count-approval.json", payload)
        with self.assertRaisesRegex(
            ValueError, "Safe import approval count contract mismatch"
        ):
            validate_import_approval(
                path=path,
                expected_sha256=sha,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                identity_plan_sha256=self.plan_sha,
            )

    def test_safe_import_approval_cannot_enable_review_seed(self) -> None:
        payload = json.loads(json.dumps(self.approval))
        payload["permissions"]["review_seed"] = True
        path, sha = self._write("unsafe-approval.json", payload)
        with self.assertRaisesRegex(ValueError, "permissions mismatch"):
            validate_import_approval(
                path=path,
                expected_sha256=sha,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                identity_plan_sha256=self.plan_sha,
            )

    def test_safe_import_approval_binds_identity_plan_sha(self) -> None:
        with self.assertRaisesRegex(ValueError, "identity-plan SHA mismatch"):
            validate_import_approval(
                path=self.approval_path,
                expected_sha256=self.approval_sha,
                flyer_key=self.flyer_key,
                scan_name=self.scan,
                raw_sha256=self.raw_sha,
                pdf_sha256=self.pdf_sha,
                identity_plan_sha256="0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
