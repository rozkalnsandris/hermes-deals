from __future__ import annotations

import base64
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_visual_review_reconciliation.py"
SPEC = importlib.util.spec_from_file_location(
    "netto_visual_review_reconciliation",
    TOOL,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NettoVisualReviewReconciliationTest(unittest.TestCase):
    def first_review(self) -> dict[str, object]:
        rows = []
        for index in range(100):
            campaign = "hz31_hasb_4" if index < 26 else "hz32_hasb"
            rows.append(
                {
                    "cell_id": f"cell-{index:03d}",
                    "campaign_id": campaign,
                    "page_number": 14 if index < 26 else 37,
                    "visual_index": index,
                    "expected_title_first_pass": f"Product {index}",
                    "expected_price_eur_first_pass": f"{index + 1}.90",
                    "title_verdict": "provisional_correct",
                    "price_verdict": "provisional_correct",
                }
            )
        return {
            "source_archive_sha256": MODULE.EXPECTED_SOURCE_ARCHIVE_SHA256,
            "source_fixture_manifest_sha256": (
                MODULE.EXPECTED_FIXTURE_MANIFEST_SHA256
            ),
            "page_count": 17,
            "cell_count": 100,
            "campaign_cell_counts": {"hz31_hasb_4": 26, "hz32_hasb": 74},
            "review_only_default": True,
            "automatic_approval_enabled": False,
            "automatic_publish_enabled": False,
            "database_write_performed": False,
            "deployment_performed": False,
            "production_apply_authorized": False,
            "rows": rows,
        }

    def compressed_first_review(self) -> dict[str, object]:
        raw = self.first_review()
        fields = [
            "card_id",
            "campaign_id",
            "page_number",
            "visual_index",
            "expected_title",
            "expected_price",
            "title_verdict",
            "price_verdict",
        ]
        encoded_rows = []
        for row in raw["rows"]:
            encoded_rows.append(
                [
                    row["cell_id"],
                    row["campaign_id"],
                    row["page_number"],
                    row["visual_index"],
                    row["expected_title_first_pass"],
                    row["expected_price_eur_first_pass"],
                    row["title_verdict"],
                    row["price_verdict"],
                ]
            )
        decoded = {
            "strategy": "netto_visual_shadow_corpus_v1",
            "source_archive_sha256": raw["source_archive_sha256"],
            "source_fixture_manifest_sha256": raw[
                "source_fixture_manifest_sha256"
            ],
            "page_count": raw["page_count"],
            "cell_count": raw["cell_count"],
            "campaign_cell_counts": raw["campaign_cell_counts"],
            "safety": {
                "review_only_default": True,
                "automatic_approval_enabled": False,
                "automatic_publish_enabled": False,
                "database_write_performed": False,
                "deployment_performed": False,
                "production_apply_authorized": False,
            },
            "row_fields": fields,
            "rows": encoded_rows,
        }
        decoded_bytes = json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        packed = gzip.compress(decoded_bytes, mtime=0)
        return {
            "strategy": "netto_visual_shadow_corpus_v1_gzip",
            "encoding": "gzip+base64",
            "payload_chunks": [base64.b64encode(packed).decode("ascii")],
            "payload_sha256": sha256(packed).hexdigest(),
            "decoded_sha256": sha256(decoded_bytes).hexdigest(),
        }

    def second_review(self) -> dict[str, object]:
        rows = []
        for index in range(100):
            campaign = "hz31_hasb_4" if index < 26 else "hz32_hasb"
            rows.append(
                {
                    "cell_id": f"cell-{index:03d}",
                    "publication_slug": campaign,
                    "page_number": 14 if index < 26 else 37,
                    "visual_index": index + 1,
                    "expected_title": f"Product {index}",
                    "expected_primary_price_eur": f"{index + 1}.90",
                    "visual_verdict": "visually_coherent_target_candidate",
                    "automatic_approval_allowed": False,
                    "automatic_publish_allowed": False,
                }
            )
        return {
            "source_n9_fixture_manifest_sha256": (
                MODULE.EXPECTED_FIXTURE_MANIFEST_SHA256
            ),
            "reviewed_page_count": 17,
            "reviewed_cell_count": 100,
            "target_or_review_cell_count": 98,
            "scope_control_count": 2,
            "automatic_approval": False,
            "automatic_publish": False,
            "production_write_performed": False,
            "cell_reviews": rows,
        }

    def test_complete_agreement_still_does_not_promote(self) -> None:
        result = MODULE.reconcile_reviews(self.first_review(), self.second_review())

        self.assertEqual(result["identity_match_count"], 100)
        self.assertEqual(result["title_exact_agreement_count"], 100)
        self.assertEqual(result["price_agreement_count"], 100)
        self.assertEqual(result["row_disagreement_count"], 0)
        self.assertEqual(result["reconciliation_status"], "reconciled_consistent")
        self.assertFalse(result["adjudication_required"])
        self.assertFalse(result["promotion_ready"])
        self.assertFalse(result["automatic_approval_enabled"])
        self.assertFalse(result["automatic_publish_enabled"])
        self.assertFalse(result["database_write_performed"])
        self.assertFalse(result["deployment_performed"])

    def test_existing_compressed_shadow_shape_is_supported(self) -> None:
        result = MODULE.reconcile_reviews(
            self.compressed_first_review(),
            self.second_review(),
        )

        self.assertEqual(result["identity_match_count"], 100)
        self.assertEqual(result["row_disagreement_count"], 0)
        self.assertFalse(result["promotion_ready"])

    def test_title_disagreement_is_reported_and_blocked(self) -> None:
        second = self.second_review()
        second["cell_reviews"][7]["expected_title"] = "Different Product"

        result = MODULE.reconcile_reviews(self.first_review(), second)

        self.assertEqual(result["title_disagreement_count"], 1)
        self.assertEqual(result["price_disagreement_count"], 0)
        self.assertEqual(result["row_disagreement_count"], 1)
        self.assertTrue(result["adjudication_required"])
        self.assertFalse(result["promotion_ready"])
        self.assertEqual(result["disagreements"][0]["cell_id"], "cell-007")

    def test_editorial_title_difference_is_visible_but_normalized(self) -> None:
        first = self.first_review()
        second = self.second_review()
        first["rows"][4]["expected_title_first_pass"] = "Product—4"
        second["cell_reviews"][4]["expected_title"] = "product 4"

        result = MODULE.reconcile_reviews(first, second)

        self.assertEqual(result["title_exact_agreement_count"], 99)
        self.assertEqual(result["title_normalized_agreement_count"], 100)
        self.assertEqual(result["row_disagreement_count"], 1)
        self.assertFalse(result["promotion_ready"])

    def test_equivalent_decimal_prices_agree(self) -> None:
        second = self.second_review()
        second["cell_reviews"][0]["expected_primary_price_eur"] = "1,9"

        result = MODULE.reconcile_reviews(self.first_review(), second)

        self.assertEqual(result["price_agreement_count"], 100)
        self.assertEqual(result["row_disagreement_count"], 0)

    def test_identity_drift_fails_closed(self) -> None:
        second = self.second_review()
        second["cell_reviews"][0]["page_number"] = 99

        with self.assertRaisesRegex(
            MODULE.ReviewReconciliationError,
            "identity drift",
        ):
            MODULE.reconcile_reviews(self.first_review(), second)

    def test_cell_set_drift_fails_closed(self) -> None:
        second = self.second_review()
        second["cell_reviews"][0]["cell_id"] = "unexpected-cell"

        with self.assertRaisesRegex(
            MODULE.ReviewReconciliationError,
            "cell ID sets differ",
        ):
            MODULE.reconcile_reviews(self.first_review(), second)

    def test_duplicate_first_review_cell_fails_closed(self) -> None:
        first = self.first_review()
        first["rows"][1]["cell_id"] = first["rows"][0]["cell_id"]

        with self.assertRaisesRegex(
            MODULE.ReviewReconciliationError,
            "cell IDs must be unique",
        ):
            MODULE.reconcile_reviews(first, self.second_review())

    def test_unsafe_first_review_flag_fails_closed(self) -> None:
        first = self.first_review()
        first["automatic_publish_enabled"] = True

        with self.assertRaisesRegex(
            MODULE.ReviewReconciliationError,
            "automatic_publish_enabled must be false",
        ):
            MODULE.reconcile_reviews(first, self.second_review())

    def test_unsafe_second_review_row_fails_closed(self) -> None:
        second = self.second_review()
        second["cell_reviews"][5]["automatic_approval_allowed"] = True

        with self.assertRaisesRegex(
            MODULE.ReviewReconciliationError,
            "approval must remain blocked",
        ):
            MODULE.reconcile_reviews(self.first_review(), second)

    def test_wrong_source_binding_fails_closed(self) -> None:
        first = self.first_review()
        first["source_archive_sha256"] = "0" * 64

        with self.assertRaisesRegex(
            MODULE.ReviewReconciliationError,
            "source archive SHA mismatch",
        ):
            MODULE.reconcile_reviews(first, self.second_review())


if __name__ == "__main__":
    unittest.main()
