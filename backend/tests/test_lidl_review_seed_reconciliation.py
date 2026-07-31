from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.lidl_review_seed_reconciliation import (
    load_review_seed_plan,
    review_entry_from_row,
)

FLYER_KEY = "20260803-20260808-r21-c20598d30ff5"
SCAN = "v631-7191e910f07b"
RAW_SHA = "eaf06bb50460c3d8842a06f09df39b7ab497c83974c8b28a8db09490068eb652"
PDF_SHA = "c20598d30ff56ce4580c16473b9fc3fdae33649ba32925355d07d8b49c367eb5"
SNAPSHOT_ID = "023bf4e5-55c1-546b-8d01-1dc6cd8345ef"


class LidlReviewSeedReconciliationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rows = self._rows()
        self.plan = self._plan(self.rows)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _row(ordinal: int, scope: str) -> dict[str, str]:
        return {
            "page": str(1 + ordinal % 69),
            "product_name": f"TEST Review Product {ordinal}",
            "package_text": "Packung",
            "price_eur": f"{1 + ordinal / 100:.2f}",
            "regular_price_eur": "",
            "regular_price_source": "",
            "app_price_eur": "",
            "valid_from": "2026-08-03",
            "valid_until": "2026-08-08",
            "validity_source": "flyer_default",
            "channel": "physical_store",
            "channel_source": "test",
            "scope": scope,
            "scope_source": "test",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "False",
            "comparison_eligible_shadow": "True",
            "r6_classification": "review",
            "recovery_source": "",
            "warnings": '["scope_requires_review"]' if scope != "excluded" else "[]",
            "manual_reviewed": "False",
            "manual_corrections": "{}",
        }

    def _rows(self) -> list[dict[str, str]]:
        rows = []
        for ordinal in range(1, 149):
            if ordinal <= 44:
                scope = "excluded"
            else:
                scope = "review"
            rows.append(self._row(ordinal, scope))
        return rows

    def _plan(self, rows: list[dict[str, str]]) -> dict[str, object]:
        entries = [
            review_entry_from_row(
                scan_name=SCAN,
                ordinal=ordinal,
                row=rows[ordinal - 1],
            )
            for ordinal in range(92, 149)
        ]
        return {
            "schema_version": 1,
            "workflow_version": "lidl-reconciled-review-seed-plan-v1",
            "decision": "ready_for_controlled_filtered_review_seed",
            "flyer_key": FLYER_KEY,
            "scan": SCAN,
            "source": {
                "raw_sha256": RAW_SHA,
                "pdf_sha256": PDF_SHA,
                "snapshot_id": SNAPSHOT_ID,
            },
            "counts": {
                "authoritative_review_rows": 148,
                "scope_excluded_rows": 44,
                "review_seed_candidates_before_reconciliation": 104,
                "suppressed_existing_approved_rows": 47,
                "new_review_items": 57,
                "new_variable_weight_rows": 0,
            },
            "permissions": {
                "review_seed": True,
                "offer_candidate_write": False,
                "auto_approve": False,
                "auto_publish": False,
                "delete_existing_rows": False,
                "update_existing_rows": False,
                "systemd_change": False,
                "timer_install": False,
            },
            "entries": entries,
        }

    def _write(self, payload: dict[str, object] | None = None) -> tuple[Path, str]:
        path = self.root / "review-seed-plan.json"
        raw = (
            json.dumps(
                payload or self.plan,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def _load(
        self,
        *,
        payload: dict[str, object] | None = None,
        rows: list[dict[str, str]] | None = None,
        expected_sha: str | None = None,
    ):
        path, actual_sha = self._write(payload)
        return load_review_seed_plan(
            path=path,
            expected_sha256=expected_sha or actual_sha,
            flyer_key=FLYER_KEY,
            scan_name=SCAN,
            raw_sha256=RAW_SHA,
            pdf_sha256=PDF_SHA,
            snapshot_id=SNAPSHOT_ID,
            review_rows=rows or self.rows,
        )

    def test_exact_filtered_review_seed_plan_is_accepted(self) -> None:
        plan = self._load()
        self.assertEqual(len(plan.entries), 57)
        self.assertEqual(plan.entries[0]["review_row_ordinal"], 92)
        self.assertEqual(plan.entries[-1]["review_row_ordinal"], 148)

    def test_plan_sha_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            self._load(expected_sha="0" * 64)

    def test_source_identity_mismatch_is_rejected(self) -> None:
        payload = copy.deepcopy(self.plan)
        payload["source"]["snapshot_id"] = "00000000-0000-0000-0000-000000000000"
        with self.assertRaisesRegex(ValueError, "source identity"):
            self._load(payload=payload)

    def test_unsafe_permissions_are_rejected(self) -> None:
        payload = copy.deepcopy(self.plan)
        payload["permissions"]["auto_publish"] = True
        with self.assertRaisesRegex(ValueError, "permissions"):
            self._load(payload=payload)

    def test_review_row_drift_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[91]["price_eur"] = "99.99"
        with self.assertRaisesRegex(ValueError, "row drift"):
            self._load(rows=rows)

    def test_duplicate_plan_identity_is_rejected(self) -> None:
        payload = copy.deepcopy(self.plan)
        payload["entries"][1] = copy.deepcopy(payload["entries"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self._load(payload=payload)

    def test_variable_weight_seed_entry_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[91]["price_basis"] = "variable_weight_example"
        payload = self._plan(rows)
        with self.assertRaisesRegex(ValueError, "fixed pricing"):
            self._load(payload=payload, rows=rows)

    def test_scope_partition_drift_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[0]["scope"] = "review"
        with self.assertRaisesRegex(ValueError, "scope partition"):
            self._load(rows=rows)

    def test_entry_field_set_drift_is_rejected(self) -> None:
        payload = copy.deepcopy(self.plan)
        payload["entries"][0]["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "field set"):
            self._load(payload=payload)


if __name__ == "__main__":
    unittest.main()
