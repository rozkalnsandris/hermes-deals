from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest
from uuid import uuid4

from app.lidl_weekly_semantics import (
    PriceObservation,
    SEMANTIC_GATE_VERSION,
    apply_reviewed_weekly_eligibility,
    bind_card_prices,
    canonical_evidence_manifest,
    classify_known_false_negative,
    gate_parser_report,
    variable_weight_fields,
)
from app.schemas import OfferCandidate, SourceChain


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "lidl"
    / "issue_23_semantic_regressions_v1.json"
)


def fixed_row(**overrides):
    row = {
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
    row.update(overrides)
    return row


class LidlWeeklySemanticsTest(unittest.TestCase):
    def test_runtime_report_is_fail_closed_without_review_profile(self) -> None:
        report = gate_parser_report(
            {
                "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
                "shadow_rows": [fixed_row()],
            }
        )
        self.assertEqual(report["semantic_gate_version"], SEMANTIC_GATE_VERSION)
        self.assertEqual(report["semantic_gate"]["parser_ready_count"], 1)
        self.assertEqual(report["semantic_gate"]["production_ready_count"], 0)
        row = report["shadow_rows"][0]
        self.assertTrue(row["parser_production_ready_shadow"])
        self.assertFalse(row["production_ready_shadow"])
        self.assertIn(
            "weekly_page_role_profile_not_reviewed",
            row["semantic_gate_reasons"],
        )

    def test_reviewed_target_page_can_release_fixed_package(self) -> None:
        decision = apply_reviewed_weekly_eligibility(
            fixed_row(),
            target_pages={1, 2},
            page_role_reviewed=True,
        )
        self.assertTrue(decision.production_ready)
        self.assertTrue(decision.comparison_eligible)
        self.assertEqual(decision.reasons, ())
        self.assertEqual(decision.row["pricing_mode"], "fixed_package")

    def test_out_of_target_page_never_becomes_production_ready(self) -> None:
        decision = apply_reviewed_weekly_eligibility(
            fixed_row(page=7),
            target_pages={1, 2},
            page_role_reviewed=True,
        )
        self.assertFalse(decision.production_ready)
        self.assertIn(
            "outside_reviewed_weekly_target_pages",
            decision.reasons,
        )

    def test_online_only_and_nonphysical_rows_fail_closed(self) -> None:
        decision = apply_reviewed_weekly_eligibility(
            fixed_row(
                channel="online_only",
                structured_online_column_signal=True,
            ),
            target_pages={1},
            page_role_reviewed=True,
        )
        self.assertFalse(decision.production_ready)
        self.assertIn("online_only", decision.reasons)
        self.assertIn("not_physical_store", decision.reasons)

    def test_unreviewed_shared_scope_does_not_inherit_parser_page_consensus(self) -> None:
        decision = apply_reviewed_weekly_eligibility(
            fixed_row(product_name="LANGNESE Magnum"),
            target_pages={1},
            page_role_reviewed=True,
            product_reviewed=False,
        )
        self.assertFalse(decision.production_ready)
        self.assertIn(
            "shared_scope_requires_product_review",
            decision.reasons,
        )

    def test_variable_weight_fields_are_lossless_and_api_compatible(self) -> None:
        fields = variable_weight_fields(
            {
                "price_basis": "variable_weight_example",
                "price_eur": "4.50",
                "unit_price_candidates_eur_per_kg": ["9.00"],
            }
        )
        self.assertEqual(fields["pricing_mode"], "example_total_plus_unit")
        self.assertEqual(fields["unit_price_eur"], "9.0000")
        self.assertEqual(fields["unit_label"], "kg")
        self.assertEqual(fields["basis_quantity"], "1.0000")
        self.assertEqual(fields["basis_unit"], "kg")
        self.assertEqual(fields["example_price_eur"], "4.50")
        self.assertEqual(fields["example_weight_g"], "500.00")
        self.assertTrue(fields["variable_weight_complete"])

        offer = OfferCandidate(
            source_chain=SourceChain.LIDL,
            source_store_external_id="DE06664",
            source_store_name="Lidl Husener Straße 44, Dortmund",
            source_offer_id="fixture-variable-weight",
            product_name_raw="Rinderhackfleisch",
            package_text_raw="Preis nach Gewicht",
            price_eur=Decimal(fields["example_price_eur"]),
            unit_price_eur=Decimal(fields["unit_price_eur"]),
            unit_label=fields["unit_label"],
            pricing_mode=fields["pricing_mode"],
            example_weight_g=Decimal(fields["example_weight_g"]),
            source_url="https://www.lidl.de/",
            snapshot_id=uuid4(),
            collected_at=datetime.now(timezone.utc),
            parser_version="lidl-v631-semantic-v1",
        )
        self.assertEqual(offer.pricing_mode, "example_total_plus_unit")
        self.assertEqual(offer.example_weight_g, Decimal("500.00"))

    def test_variable_weight_requires_product_review_before_release(self) -> None:
        row = fixed_row(
            product_name="Rinderhackfleisch",
            price_eur="4.50",
            price_basis="variable_weight_example",
            unit_price_candidates_eur_per_kg=["9.00"],
        )
        blocked = apply_reviewed_weekly_eligibility(
            row,
            target_pages={1},
            page_role_reviewed=True,
            product_reviewed=False,
        )
        self.assertFalse(blocked.production_ready)
        self.assertIn(
            "variable_weight_requires_product_review",
            blocked.reasons,
        )

        released = apply_reviewed_weekly_eligibility(
            row,
            target_pages={1},
            page_role_reviewed=True,
            product_reviewed=True,
        )
        self.assertTrue(released.production_ready)
        self.assertTrue(released.comparison_eligible)
        self.assertEqual(
            released.row["pricing_mode"],
            "example_total_plus_unit",
        )

    def test_ambiguous_variable_weight_unit_candidates_remain_review_only(self) -> None:
        decision = apply_reviewed_weekly_eligibility(
            fixed_row(
                product_name="Rinderhackfleisch",
                price_eur="4.50",
                price_basis="variable_weight_example",
                unit_price_candidates_eur_per_kg=["8.00", "9.00"],
            ),
            target_pages={1},
            page_role_reviewed=True,
            product_reviewed=True,
        )
        self.assertFalse(decision.production_ready)
        self.assertIn(
            "variable_weight_unit_price_ambiguous",
            decision.reasons,
        )

    def test_adjacent_card_prices_do_not_leak(self) -> None:
        observations = [
            PriceObservation("store", "1.49", (60, 70, 90, 90)),
            PriceObservation(
                "regular",
                "1.99",
                (60, 45, 90, 60),
                "Normalpreis",
            ),
            PriceObservation(
                "app",
                "1.29",
                (60, 95, 90, 115),
                "Lidl Plus",
            ),
            PriceObservation("store", "2.49", (160, 70, 190, 90)),
            PriceObservation(
                "regular",
                "2.99",
                (160, 45, 190, 60),
                "Normalpreis",
            ),
        ]
        left = bind_card_prices(
            card_bbox=(0, 0, 100, 130),
            observations=observations,
        )
        right = bind_card_prices(
            card_bbox=(110, 0, 210, 130),
            observations=observations,
        )
        self.assertEqual(
            left,
            {
                "price_eur": "1.49",
                "regular_price_eur": "1.99",
                "app_price_eur": "1.29",
            },
        )
        self.assertEqual(
            right,
            {
                "price_eur": "2.49",
                "regular_price_eur": "2.99",
                "app_price_eur": None,
            },
        )

    def test_unlabelled_reference_price_is_not_owned(self) -> None:
        result = bind_card_prices(
            card_bbox=(0, 0, 100, 100),
            observations=[
                PriceObservation("store", "1.49", (10, 70, 40, 90)),
                PriceObservation("regular", "1.99", (10, 40, 40, 60)),
            ],
        )
        self.assertEqual(result["price_eur"], "1.49")
        self.assertIsNone(result["regular_price_eur"])

    def test_multiple_owned_store_prices_are_ambiguous(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous store"):
            bind_card_prices(
                card_bbox=(0, 0, 100, 100),
                observations=[
                    PriceObservation("store", "1.49", (10, 70, 40, 90)),
                    PriceObservation("store", "2.49", (50, 70, 80, 90)),
                ],
            )

    def test_known_false_negative_fixture_has_explicit_outcomes(self) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["cases"]), 4)
        for case in payload["cases"]:
            result = classify_known_false_negative(
                title=case["title"],
                structured_category_text=case.get(
                    "structured_category_text",
                    "",
                ),
            )
            self.assertEqual(result["scope"], case["expected_scope"])
            self.assertEqual(result["reason"], case["expected_reason"])
            self.assertTrue(result["review_required"])
            self.assertFalse(result["production_ready"])

    def test_canonical_runtime_uses_semantic_gated_shadow_proxy(self) -> None:
        import sys

        tools = Path(__file__).resolve().parents[2] / "tools"
        sys.path.insert(0, str(tools))
        try:
            from lidl_parser_provenance.lidl_v631_runtime import (
                SemanticGatedShadowRuntime,
                load_lidl_v631,
            )

            runtime = load_lidl_v631()
            self.assertIsInstance(runtime.shadow, SemanticGatedShadowRuntime)
            self.assertEqual(
                runtime.shadow.PARSER_VERSION,
                "lidl-pdf-v08c-r61-shadow-v631",
            )
            self.assertEqual(
                runtime.shadow.raw_module.PARSER_VERSION,
                runtime.shadow.PARSER_VERSION,
            )
        finally:
            sys.path.remove(str(tools))

    def test_evidence_manifest_is_order_independent_and_sorted(self) -> None:
        first_raw, first_sha = canonical_evidence_manifest(
            {"z.log": b"z", "a/report.json": b"a"}
        )
        second_raw, second_sha = canonical_evidence_manifest(
            {"a/report.json": b"a", "z.log": b"z"}
        )
        self.assertEqual(first_raw, second_raw)
        self.assertEqual(first_sha, second_sha)
        payload = json.loads(first_raw)
        self.assertEqual(
            [entry["path"] for entry in payload["entries"]],
            ["a/report.json", "z.log"],
        )

    def test_evidence_manifest_rejects_unsafe_and_case_colliding_paths(self) -> None:
        with self.assertRaises(ValueError):
            canonical_evidence_manifest({"../escape": b"x"})
        with self.assertRaises(ValueError):
            canonical_evidence_manifest({"A.log": b"a", "a.log": b"b"})


if __name__ == "__main__":
    unittest.main()
