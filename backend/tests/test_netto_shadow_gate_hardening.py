from __future__ import annotations

from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
import unittest


TOOL = Path(__file__).resolve().parents[2] / "tools" / "netto_weekly_shadow.py"
SPEC = importlib.util.spec_from_file_location("netto_weekly_shadow_gate_hardening", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

POLICY_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "netto"
    / "n25_title_package_review_policy_v1.json"
)


def _sha(char: str) -> str:
    return char * 64


def _row(campaign: str, field: str, index: int) -> dict[str, object]:
    value = f"value-{index}"
    return {
        "campaign_id": campaign,
        "field": field,
        "expected": value,
        "predicted": value,
        "classification": "match",
        "page_number": index + 1,
        "card_id": f"{campaign}-{field}-{index}",
        "manifest_sha256": _sha("a"),
        "pdf_sha256": _sha("c"),
        "parser_identity": "netto-parser@abc123",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
    }


class NettoShadowGateHardeningTest(unittest.TestCase):
    def test_imported_n25_n26_policy_remains_bound_to_default_review_gates(self):
        policy = json.loads(POLICY_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(
            Decimal(str(policy["thresholds"]["automatic_title_full_coverage_minimum"])),
            MODULE.DEFAULT_PRECISION_THRESHOLDS["title"],
        )
        self.assertEqual(
            Decimal(str(policy["thresholds"]["automatic_package_selection_minimum"])),
            MODULE.DEFAULT_PRECISION_THRESHOLDS["package"],
        )
        self.assertLess(
            Decimal(str(policy["basis"]["combined_full_title_rate"])),
            MODULE.DEFAULT_PRECISION_THRESHOLDS["title"],
        )
        self.assertEqual(policy["basis"]["automatic_package_selection_count"], 0)
        self.assertFalse(policy["promotion_policy"]["production_integration_allowed"])

    def test_each_field_requires_multiple_campaign_families(self):
        rows = [_row("n25", "title", index) for index in range(5)]
        rows.append(_row("n26", "package", 20))
        report = MODULE.evaluate_corpus(
            rows,
            minimum_samples=5,
            thresholds={"title": Decimal("0.90")},
            coverage_thresholds={"title": Decimal("0.90")},
        )
        title = report["fields"]["title"]
        self.assertEqual(title["campaign_ids"], ["n25"])
        self.assertEqual(title["campaign_count"], 1)
        self.assertEqual(title["minimum_campaigns"], 2)
        self.assertFalse(title["promoted"])
        self.assertEqual(title["route"], "review_required")

    def test_corpus_identity_is_order_independent(self):
        rows = [
            _row("n25", "title", 1),
            _row("n26", "title", 2),
        ]
        forward = MODULE.evaluate_corpus(rows, minimum_samples=1)
        reverse = MODULE.evaluate_corpus(list(reversed(rows)), minimum_samples=1)
        self.assertEqual(forward["corpus_sha256"], reverse["corpus_sha256"])
        self.assertEqual(forward["corpus_row_count"], 2)
        self.assertEqual(forward["parser_identities"], ["netto-parser@abc123"])

    def test_thresholds_must_be_probabilities(self):
        rows = [_row("n25", "title", 1), _row("n26", "title", 2)]
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            MODULE.evaluate_corpus(
                rows,
                thresholds={"title": Decimal("1.01")},
            )


if __name__ == "__main__":
    unittest.main()
