from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.lidl_weekly_completeness_contract import (
    anchor_is_owned,
    bbox_center_distance,
    classify_target_scope,
    is_online_only,
    load_weekly_target_profile,
    normalize_text,
    obvious_non_target_title,
    plausible_same_title,
    promo_or_non_product_title,
    represented_on_page,
    stable_candidate_key,
    strong_ocr_title_echo,
    text_similarity,
)


class LidlWeeklyCompletenessContractTest(unittest.TestCase):
    def test_normalize_rejoins_hyphenation(self) -> None:
        self.assertEqual(normalize_text("Walnuss- kerne"), "walnusskerne")

    def test_similarity_accepts_same_product_spacing(self) -> None:
        self.assertGreaterEqual(
            text_similarity("KINDER Maxi King", "Kinder  Maxi-King"),
            0.9,
        )

    def test_plausible_title_requires_shared_significant_token(self) -> None:
        self.assertTrue(plausible_same_title("LANGNESE Magnum", "Langnese Magnum"))
        self.assertFalse(plausible_same_title("Magnum", "Garantie"))

    def test_anchor_ownership_uses_price_page_and_geometry(self) -> None:
        owned = [
            {"page": 16, "price_eur": "1.59", "bbox": [10, 20, 50, 60]}
        ]
        self.assertTrue(
            anchor_is_owned(
                page=16,
                price_eur="1.59",
                bbox=[11, 20, 51, 60],
                owned=owned,
            )
        )
        self.assertFalse(
            anchor_is_owned(
                page=16,
                price_eur="2.59",
                bbox=[11, 20, 51, 60],
                owned=owned,
            )
        )

    def test_represented_is_page_scoped(self) -> None:
        represented = {1: {"Buttercroissant"}}
        self.assertTrue(
            represented_on_page(
                page=1,
                title="Buttercroissant",
                represented=represented,
            )
        )
        self.assertFalse(
            represented_on_page(
                page=2,
                title="Buttercroissant",
                represented=represented,
            )
        )

    def test_non_target_filter_is_generic_category_signal(self) -> None:
        self.assertTrue(obvious_non_target_title("Akku-Bohrschrauber 20 V"))
        self.assertFalse(obvious_non_target_title("KINDER Maxi King"))

    def test_bbox_distance_is_deterministic(self) -> None:
        self.assertEqual(
            round(bbox_center_distance([0, 0, 10, 10], [3, 4, 13, 14]), 3),
            5.0,
        )

    def test_review_profile_is_authoritative_page_role_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "schema_version": 1,
                "status": "reviewed",
                "target_kind": "weekly_physical_deals",
                "target_pages": [1, 12, 16, 64],
                "baseline_pages": [2, 3],
            }
            raw = json.dumps(payload, sort_keys=True).encode("utf-8")
            (root / "review-profile.json").write_bytes(raw)

            profile = load_weekly_target_profile(root, page_count=69)
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile["target_pages"], [1, 12, 16, 64])
            self.assertEqual(profile["target_kind"], "weekly_physical_deals")
            self.assertEqual(profile["status"], "reviewed")
            self.assertEqual(len(profile["sha256"]), 64)
            self.assertNotIn(2, profile["target_pages"])

    def test_review_profile_rejects_invalid_page_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "review-profile.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "reviewed",
                        "target_kind": "weekly_physical_deals",
                        "target_pages": [1, 1, 70],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_weekly_target_profile(root, page_count=69)

    def test_review_profile_page_role_does_not_require_product_truth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "review-profile.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "reviewed",
                        "target_kind": "weekly_physical_deals",
                        "target_pages": [1],
                    }
                ),
                encoding="utf-8",
            )
            profile = load_weekly_target_profile(root, page_count=69)
            assert profile is not None
            self.assertEqual(profile["target_pages"], [1])
            self.assertNotIn("products", profile)

    def test_unknown_title_remains_review_not_false_truth(self) -> None:
        self.assertEqual(
            classify_target_scope(title="ALESTO Walnusskerne"),
            "review",
        )

    def test_candidate_key_is_stable(self) -> None:
        kwargs = dict(
            flyer_key="f",
            scan="scan-1",
            lane="native_unowned_price",
            page=16,
            title="KINDER Maxi King",
            price_eur="1.59",
            bbox=[1, 2, 3, 4],
        )
        self.assertEqual(stable_candidate_key(**kwargs), stable_candidate_key(**kwargs))

    def test_candidate_key_changes_with_lane(self) -> None:
        common = dict(
            flyer_key="f",
            scan="scan-1",
            page=1,
            title="LANGNESE Magnum",
            price_eur=None,
            bbox=[1, 2, 3, 4],
        )
        self.assertNotEqual(
            stable_candidate_key(lane="native_sparse_title", **common),
            stable_candidate_key(lane="native_unowned_price", **common),
        )

    def test_scope_accepts_food_title(self) -> None:
        self.assertEqual(
            classify_target_scope(title="Buttercroissant"),
            "in_scope",
        )

    def test_scope_accepts_structured_food_category(self) -> None:
        self.assertEqual(
            classify_target_scope(
                title="KINDER Maxi King",
                structured_category_text="Lebensmittel > Süßwaren",
            ),
            "in_scope",
        )

    def test_scope_excludes_durable_household(self) -> None:
        self.assertEqual(
            classify_target_scope(title="GSW Energiespartopf"),
            "excluded",
        )

    def test_scope_keeps_household_consumable(self) -> None:
        self.assertEqual(
            classify_target_scope(title="FORMIL Waschmittel"),
            "in_scope",
        )

    def test_online_only_evidence_is_fail_closed(self) -> None:
        self.assertTrue(is_online_only(local_text="nur online"))
        self.assertTrue(is_online_only(structured_online_signal=True))
        self.assertFalse(is_online_only(local_text="auch online"))

    def test_promo_labels_are_not_product_titles(self) -> None:
        self.assertTrue(promo_or_non_product_title("pro Monat"))
        self.assertTrue(promo_or_non_product_title("Mit Lidl Plus"))
        self.assertFalse(promo_or_non_product_title("LANGNESE Magnum"))

    def test_structured_school_bag_category_is_excluded(self) -> None:
        self.assertEqual(
            classify_target_scope(
                title="LUPILU Kinder-Rucksack",
                structured_category_text=(
                    "Kinderwelt Kinder- & Babyausstattung Schule "
                    "Schulranzen & Schultaschen Spielware"
                ),
            ),
            "excluded",
        )

    def test_entsafter_is_not_food_because_of_saft_substring(self) -> None:
        self.assertEqual(
            classify_target_scope(title="SEVERIN Entsafter"),
            "excluded",
        )

    def test_unknown_food_brand_title_can_stay_review(self) -> None:
        self.assertEqual(
            classify_target_scope(title="KINDER Maxi King"),
            "review",
        )

    def test_bounded_ocr_can_echo_unknown_title(self) -> None:
        self.assertTrue(
            strong_ocr_title_echo(
                "LANGNESE Magnum",
                "LANGNESE Magnum\nVerschiedene Sorten\n2,49",
            )
        )

    def test_bounded_ocr_does_not_echo_unrelated_title(self) -> None:
        self.assertFalse(
            strong_ocr_title_echo(
                "LANGNESE Magnum",
                "LUPILU Paw Patrol Rucksack",
            )
        )


if __name__ == "__main__":
    unittest.main()
