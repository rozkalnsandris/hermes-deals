from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from app.lidl_weekly_semantics import gate_parser_report, semantic_row_key

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO_ROOT / "tools" / "lidl_weekly_semantic_view.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("lidl_semantic_view_test", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load semantic view tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offer(**changes):
    result = {
        "page": 1,
        "product_name": "Buttercroissant",
        "price_eur": "1.49",
        "regular_price_eur": None,
        "regular_price_source": None,
        "app_price_eur": None,
        "app_valid_from": None,
        "app_valid_until": None,
        "channel": "physical_store",
        "scope": "in_scope",
        "price_basis": "fixed_or_explicit",
        "production_ready_shadow": True,
        "comparison_eligible_shadow": True,
    }
    result.update(changes)
    return result


class LidlWeeklySemanticViewTest(unittest.TestCase):
    def fixture(self, root: Path, *, review_key: str | None = None):
        flyer = root / "flyer"
        scan = flyer / "scans" / "scan-1"
        scan.mkdir(parents=True)
        rows = [
            offer(),
            offer(product_name="LANGNESE Magnum"),
            offer(page=2),
            offer(channel="online_only"),
            offer(
                product_name="Rinderhackfleisch",
                price_eur="4.50",
                price_basis="variable_weight_example",
                unit_price_candidates_eur_per_kg=["9.00"],
            ),
        ]
        gated = gate_parser_report({"shadow_rows": rows})["shadow_rows"]
        variable_key = semantic_row_key(gated[-1])
        approved_key = review_key or variable_key
        profile = {
            "schema_version": 1,
            "status": "reviewed",
            "target_kind": "weekly_physical_deals",
            "target_pages": [1],
            "baseline_pages": [2],
            "excluded_page_roles": {"editorial": [3]},
            "unit_basis_reviews": [{
                "row_sha256": approved_key,
                "decision": "approve_unit_basis_semantics",
                "reviewed_by": "fixture-reviewer",
                "reviewed_at": "2026-08-05T09:00:00Z",
                "note": "Exact unit basis reviewed."
            }]
        }
        (flyer / "review-profile.json").write_text(
            json.dumps(profile, sort_keys=True) + "\n", encoding="utf-8"
        )
        (scan / "corrected-rows.json").write_text(
            json.dumps(gated, sort_keys=True) + "\n", encoding="utf-8"
        )
        (scan / "summary.json").write_text(
            json.dumps({
                "flyer_key": "fixture-flyer",
                "scan": "scan-1",
                "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
                "parser_sha256": "7" * 64,
                "source": {"pdf_sha256": "a" * 64, "raw_sha256": "b" * 64}
            }, sort_keys=True) + "\n",
            encoding="utf-8"
        )
        return flyer, scan

    def test_complete_partition_has_zero_unexplained_rows(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            flyer, scan = self.fixture(root)
            result = tool.build_semantic_view(
                flyer_dir=flyer,
                scan_dir=scan,
                output_dir=root / "out",
                page_count=3,
            )
            coverage = result["coverage"]
            self.assertEqual(coverage["input_row_count"], 5)
            self.assertEqual(coverage["production_ready_count"], 2)
            self.assertEqual(coverage["review_required_count"], 1)
            self.assertEqual(coverage["excluded_count"], 2)
            self.assertEqual(coverage["explained_count"], 5)
            self.assertEqual(coverage["unexplained_count"], 0)
            self.assertFalse(coverage["database_write"])
            self.assertFalse(coverage["production_deploy"])

    def test_same_inputs_create_identical_evidence(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            flyer, scan = self.fixture(root)
            one = tool.build_semantic_view(
                flyer_dir=flyer, scan_dir=scan,
                output_dir=root / "one", page_count=3
            )
            two = tool.build_semantic_view(
                flyer_dir=flyer, scan_dir=scan,
                output_dir=root / "two", page_count=3
            )
            self.assertEqual(one["manifest_sha256"], two["manifest_sha256"])
            for name in one["files"]:
                self.assertEqual(
                    (root / "one" / name).read_bytes(),
                    (root / "two" / name).read_bytes(),
                    name,
                )

    def test_unknown_review_identity_is_rejected(self) -> None:
        tool = load_tool()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            flyer, scan = self.fixture(root, review_key="f" * 64)
            with self.assertRaisesRegex(tool.SemanticViewError, "does not match"):
                tool.build_semantic_view(
                    flyer_dir=flyer, scan_dir=scan,
                    output_dir=root / "out", page_count=3
                )


if __name__ == "__main__":
    unittest.main()
