from __future__ import annotations

import unittest

from app.lidl_weekly_semantics import (
    gate_parser_report,
    partition_weekly_rows,
    semantic_row_key,
)


def row(**overrides):
    value = {
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
        "warnings": [],
        "rejection_reasons": [],
    }
    value.update(overrides)
    return value


class LidlWeeklySemanticPartitionTest(unittest.TestCase):
    def test_profile_can_release_originally_ready_gated_row(self) -> None:
        gated = gate_parser_report({"shadow_rows": [row()]})["shadow_rows"][0]
        self.assertFalse(gated["production_ready_shadow"])
        self.assertTrue(gated["parser_production_ready_shadow"])

        partition = partition_weekly_rows(
            [gated],
            target_pages={1},
            page_role_reviewed=True,
        )
        released = partition["rows"][0]
        self.assertEqual(released["weekly_partition"], "production_ready")
        self.assertTrue(released["production_ready_shadow"])
        self.assertTrue(released["comparison_eligible_shadow"])

    def test_every_row_has_one_explained_partition(self) -> None:
        source = [
            row(),
            row(product_name="LANGNESE Magnum"),
            row(page=2),
            row(channel="online_only"),
            row(
                product_name="Rinderhackfleisch",
                price_eur="4.50",
                price_basis="variable_weight_example",
                unit_price_candidates_eur_per_kg=["9.00"],
            ),
        ]
        gated = gate_parser_report({"shadow_rows": source})["shadow_rows"]
        variable_key = semantic_row_key(gated[-1])
        result = partition_weekly_rows(
            gated,
            target_pages={1},
            page_role_reviewed=True,
            product_reviewed_row_keys={variable_key},
        )
        coverage = result["coverage"]
        self.assertEqual(coverage["input_row_count"], 5)
        self.assertEqual(coverage["unique_row_count"], 5)
        self.assertEqual(coverage["production_ready_count"], 2)
        self.assertEqual(coverage["review_required_count"], 1)
        self.assertEqual(coverage["excluded_count"], 2)
        self.assertEqual(coverage["explained_count"], 5)
        self.assertEqual(coverage["unexplained_count"], 0)
        self.assertEqual(coverage["target_page_row_count"], 4)
        self.assertEqual(coverage["out_of_target_page_row_count"], 1)
        self.assertEqual(coverage["product_reviewed_row_count"], 1)

    def test_row_identity_is_stable_before_and_after_default_gate(self) -> None:
        source = row()
        gated = gate_parser_report({"shadow_rows": [source]})["shadow_rows"][0]
        self.assertEqual(semantic_row_key(source), semantic_row_key(gated))

    def test_duplicate_parser_row_identity_fails_closed(self) -> None:
        source = row()
        with self.assertRaisesRegex(ValueError, "duplicate semantic row identity"):
            partition_weekly_rows(
                [source, dict(source)],
                target_pages={1},
                page_role_reviewed=True,
            )

    def test_parser_rejected_target_row_remains_review_required(self) -> None:
        result = partition_weekly_rows(
            [row(production_ready_shadow=False)],
            target_pages={1},
            page_role_reviewed=True,
        )
        current = result["rows"][0]
        self.assertEqual(current["weekly_partition"], "review_required")
        self.assertIn(
            "frozen_parser_not_production_ready",
            current["semantic_gate_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
