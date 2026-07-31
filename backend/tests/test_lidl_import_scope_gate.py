from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.lidl_corpus_import import (
    IMPORT_SCOPE_EXCLUDED,
    IMPORT_SCOPE_IN_SCOPE,
    IMPORT_SCOPE_REVIEW,
    accepted_excluded_rows,
    accepted_review_rows,
    build_offer,
    import_scope_decision,
    review_reason_codes,
    review_rows,
    safe_rows,
)
from app.lidl_weekly_completeness_contract import (
    classify_target_scope,
    promo_or_non_product_title,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "lidl_b15i2_scope_204.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class LidlImportScopeGateTest(unittest.TestCase):
    def test_exact_b15i2_204_row_import_partition(self) -> None:
        fixture = _fixture()
        rows = fixture["rows"]
        assert isinstance(rows, list)

        actual = Counter(import_scope_decision(dict(row)) for row in rows)
        self.assertEqual(
            actual,
            Counter(
                {
                    IMPORT_SCOPE_IN_SCOPE: 180,
                    IMPORT_SCOPE_EXCLUDED: 21,
                    IMPORT_SCOPE_REVIEW: 3,
                }
            ),
        )
        for row in rows:
            assert isinstance(row, dict)
            self.assertEqual(
                import_scope_decision(dict(row)),
                row["expected_import_scope"],
                row,
            )

    def test_shared_contract_explicitly_excludes_all_21_known_non_targets(self) -> None:
        fixture = _fixture()
        rows = fixture["rows"]
        assert isinstance(rows, list)
        excluded = [
            row
            for row in rows
            if row["expected_import_scope"] == IMPORT_SCOPE_EXCLUDED
        ]
        self.assertEqual(len(excluded), 21)
        for row in excluded:
            self.assertEqual(
                classify_target_scope(title=row["product_name"]),
                IMPORT_SCOPE_EXCLUDED,
                row,
            )

    def test_three_non_product_titles_route_to_review(self) -> None:
        fixture = _fixture()
        rows = fixture["rows"]
        assert isinstance(rows, list)
        review = [
            row
            for row in rows
            if row["expected_import_scope"] == IMPORT_SCOPE_REVIEW
        ]
        self.assertEqual(len(review), 3)
        for row in review:
            self.assertTrue(promo_or_non_product_title(row["product_name"]), row)
            self.assertEqual(import_scope_decision(dict(row)), IMPORT_SCOPE_REVIEW)

    def test_safe_review_and_excluded_helpers_preserve_exact_partition(self) -> None:
        fixture = _fixture()
        rows = fixture["rows"]
        assert isinstance(rows, list)
        fieldnames = [
            "ordinal",
            "product_name",
            "package_text",
            "channel",
            "scope",
            "scope_source",
            "price_basis",
            "production_ready_shadow",
            "warnings",
            "expected_import_scope",
        ]

        with TemporaryDirectory() as temporary:
            scan = Path(temporary)
            for filename, payload_rows in (
                ("accepted-physical.tsv", rows),
                ("review-required.tsv", []),
            ):
                with (scan / filename).open(
                    "w",
                    encoding="utf-8",
                    newline="",
                ) as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=fieldnames,
                        delimiter="\t",
                        lineterminator="\n",
                        extrasaction="raise",
                    )
                    writer.writeheader()
                    writer.writerows(payload_rows)

            self.assertEqual(len(safe_rows(scan)), 180)
            self.assertEqual(len(accepted_excluded_rows(scan)), 21)
            self.assertEqual(len(accepted_review_rows(scan)), 3)
            self.assertEqual(len(review_rows(scan)), 3)

    def test_build_offer_fails_closed_before_touching_context(self) -> None:
        excluded = {
            "product_name": "COLGATE Zahnpasta",
            "channel": "physical_store",
            "scope": "in_scope",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "True",
        }
        with self.assertRaisesRegex(ValueError, "decision=excluded"):
            build_offer(
                row=excluded,
                ordinal=1,
                context=None,  # type: ignore[arg-type]
                snapshot=None,  # type: ignore[arg-type]
            )

        review = dict(excluded, product_name="Punkte oder")
        with self.assertRaisesRegex(ValueError, "decision=review"):
            build_offer(
                row=review,
                ordinal=1,
                context=None,  # type: ignore[arg-type]
                snapshot=None,  # type: ignore[arg-type]
            )

    def test_import_downgrade_gets_explicit_review_reason(self) -> None:
        row = {
            "product_name": "11 Monate gereift",
            "channel": "physical_store",
            "scope": "in_scope",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "True",
            "warnings": "[]",
        }
        self.assertEqual(
            review_reason_codes(row),
            ["import_scope_requires_review"],
        )

    def test_personal_care_is_not_household_consumable(self) -> None:
        for title in (
            "COLGATE Zahnpasta",
            "OLD SPICE 3in1 Duschgel XL",
            "PALMOLIVE Creme dusche",
        ):
            self.assertEqual(classify_target_scope(title=title), "excluded")
        self.assertEqual(
            classify_target_scope(
                title="Pflegeprodukt",
                structured_category_text="Drogerie > Körperpflege",
            ),
            "excluded",
        )

    def test_household_consumables_remain_in_scope(self) -> None:
        for title in (
            "ARIEL Waschmittel",
            "KUSCHELWEICH Weichspüler",
            "SOMAT Tabs",
            "WC FRISCH Kraft Aktiv WC-Stein",
        ):
            self.assertEqual(classify_target_scope(title=title), "in_scope")

    def test_unknown_title_needs_parser_evidence_but_explicit_veto_wins(self) -> None:
        unknown = {
            "product_name": "KINDER Maxi King",
            "channel": "physical_store",
            "scope": "in_scope",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "True",
        }
        self.assertEqual(classify_target_scope(title=unknown["product_name"]), "review")
        self.assertEqual(import_scope_decision(unknown), IMPORT_SCOPE_IN_SCOPE)

        parser_review = dict(unknown, scope="review")
        self.assertEqual(import_scope_decision(parser_review), IMPORT_SCOPE_REVIEW)

        explicit_veto = dict(unknown, product_name="PAW Patrol Spielzelt")
        self.assertEqual(import_scope_decision(explicit_veto), IMPORT_SCOPE_EXCLUDED)


if __name__ == "__main__":
    unittest.main()
