from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.lidl_candidate_precision import assess_candidate, apply_strict_gate, audit_candidate_precision


class LidlCandidatePrecisionTest(unittest.TestCase):
    def test_math_verified_candidate_is_precision_ready(self) -> None:
        item = assess_candidate({
            "page": 10,
            "product_name_raw": "Hackfleisch",
            "evidence_tier": "math_verified",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 6.62,
            "keyword_overlap": ["hackfleisch"],
            "db_write_eligible": False,
        }, {"grocery_hits": ["milch"]})
        self.assertEqual(item["precision_disposition"], "precision_ready")
        self.assertFalse(item["db_write_eligible"])

    def test_correction_candidate_stays_review_only(self) -> None:
        item = assess_candidate({
            "page": 23,
            "product_name_raw": "ENNE RIGATE a",
            "evidence_tier": "math_correction_review",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 8.66,
            "keyword_overlap": ["rigate"],
            "db_write_eligible": False,
        }, {"grocery_hits": ["wein"]})
        self.assertEqual(item["precision_disposition"], "correction_review")

    def test_origin_only_label_is_rejected(self) -> None:
        item = assess_candidate({
            "page": 24,
            "product_name_raw": "Rhône/Frankreich",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 9.0,
            "keyword_overlap": ["frankreich"],
        }, {"grocery_hits": ["wein"]})
        self.assertEqual(item["precision_disposition"], "reject_noise")
        self.assertEqual(item["precision_reject_reason"], "origin_only")

    def test_package_promo_label_is_rejected(self) -> None:
        item = assess_candidate({
            "page": 25,
            "product_name_raw": "Kauf von 6 Stk.",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 8.0,
            "keyword_overlap": ["kauf"],
        }, {"grocery_hits": ["wein"]})
        self.assertEqual(item["precision_disposition"], "reject_noise")
        self.assertEqual(item["precision_reject_reason"], "package_promo_or_sentence_noise")

    def test_dangling_fragment_is_rejected(self) -> None:
        item = assess_candidate({
            "page": 9,
            "product_name_raw": "Wasser-",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 8.0,
            "keyword_overlap": ["wasser"],
        }, {"grocery_hits": ["wasser"]})
        self.assertEqual(item["precision_disposition"], "reject_noise")
        self.assertEqual(item["precision_reject_reason"], "dangling_fragment")

    def test_trailing_glue_is_trimmed_from_brand(self) -> None:
        item = assess_candidate({
            "page": 17,
            "product_name_raw": "COCA-COLA in",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 8.0,
            "keyword_overlap": ["coca", "cola"],
        }, {"grocery_hits": ["cola"]})
        self.assertEqual(item["product_name_clean"], "COCA-COLA")
        self.assertIn(item["precision_disposition"], {"semantic_high_precision", "semantic_review"})

    def test_single_word_grocery_label_can_be_high_precision(self) -> None:
        item = assess_candidate({
            "page": 23,
            "product_name_raw": "Tomaten",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 8.0,
            "keyword_overlap": ["tomaten"],
        }, {"grocery_hits": ["tomate"]})
        self.assertIn(item["precision_disposition"], {"semantic_high_precision", "semantic_review"})

    def test_audit_preserves_nonwriting_contract(self) -> None:
        source = {
            "strategy": "full_grocery_ocr_dry_run",
            "db_write_performed": False,
            "dry_run_candidate_total": 2,
            "dry_run_candidates": [
                {"page": 10, "product_name_raw": "Hackfleisch", "evidence_tier": "math_verified", "psm_support": 2, "psm_modes": [11, 12], "semantic_score": 7, "keyword_overlap": ["hackfleisch"], "db_write_eligible": False},
                {"page": 24, "product_name_raw": "Frankreich", "evidence_tier": "semantic_price_only", "psm_support": 2, "psm_modes": [11, 12], "semantic_score": 8, "keyword_overlap": ["frankreich"], "db_write_eligible": False},
            ],
            "pages": [
                {"page": 10, "selection": {"grocery_hits": ["milch"]}},
                {"page": 24, "selection": {"grocery_hits": ["wein"]}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.json"
            src.write_text(json.dumps(source), encoding="utf-8")
            report = audit_candidate_precision(full_report_path=src, output_dir=root)
            self.assertTrue(report["gate"]["all_db_write_disabled"])
            self.assertEqual(report["source_candidate_total"], 2)
            self.assertEqual(report["precision_ready_total"], 1)
            self.assertEqual(report["rejected_noise_total"], 1)
            self.assertTrue(Path(report["report_path"]).exists())

    def test_strict_gate_keeps_clean_math_verified_candidate(self) -> None:
        base = assess_candidate({
            "page": 10,
            "product_name_raw": "Hackfleisch",
            "evidence_tier": "math_verified",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 6.62,
            "keyword_overlap": ["hackfleisch"],
            "ocr_price_eur": 9.49,
            "math_expected_price_eur": 9.49,
            "db_write_eligible": False,
        }, {"grocery_hits": ["milch"]})
        item = apply_strict_gate([base])[0]
        self.assertEqual(item["strict_disposition"], "strict_ready")
        self.assertFalse(item["db_write_eligible"])

    def test_strict_gate_routes_packaging_math_label_to_review(self) -> None:
        base = assess_candidate({
            "page": 55,
            "product_name_raw": "Abtropfgewicht",
            "evidence_tier": "math_verified",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 7.0,
            "keyword_overlap": ["abtropfgewicht"],
            "ocr_price_eur": 1.29,
            "math_expected_price_eur": 1.29,
        }, {"grocery_hits": ["wasser"]})
        item = apply_strict_gate([base])[0]
        self.assertEqual(item["strict_disposition"], "strict_review")
        self.assertEqual(item["strict_reason"], "packaging_descriptor_label")

    def test_strict_gate_blocks_semantic_price_when_nearby_math_disagrees(self) -> None:
        base = assess_candidate({
            "page": 17,
            "product_name_raw": "COCA-COLA in",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 10.0,
            "keyword_overlap": ["coca", "cola"],
            "ocr_price_eur": 0.33,
            "math_expected_price_eur": 4.20,
        }, {"grocery_hits": ["cola"]})
        item = apply_strict_gate([base])[0]
        self.assertEqual(item["strict_disposition"], "strict_review")
        self.assertEqual(item["strict_reason"], "math_context_price_mismatch")

    def test_strict_gate_blocks_sub_euro_semantic_without_math(self) -> None:
        base = assess_candidate({
            "page": 25,
            "product_name_raw": "Pistazien",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 10.0,
            "keyword_overlap": ["pistazien"],
            "ocr_price_eur": 0.51,
        }, {"grocery_hits": ["pistazien"]})
        item = apply_strict_gate([base])[0]
        self.assertEqual(item["strict_disposition"], "strict_review")
        self.assertEqual(item["strict_reason"], "sub_euro_semantic_without_math")

    def test_strict_gate_keeps_alcohol_semantic_only_review_only(self) -> None:
        base = assess_candidate({
            "page": 24,
            "product_name_raw": "TAITTINGER",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 10.0,
            "keyword_overlap": ["taittinger", "champagner"],
            "ocr_price_eur": 79.0,
        }, {"grocery_hits": ["wein"]})
        item = apply_strict_gate([base])[0]
        self.assertEqual(item["strict_disposition"], "strict_review")
        self.assertEqual(item["strict_reason"], "alcohol_semantic_only_requires_review")

    def test_strict_gate_rejects_nonfood_water_false_positive(self) -> None:
        base = assess_candidate({
            "page": 50,
            "product_name_raw": "EasyFill-Filterkorb. Wasser",
            "evidence_tier": "semantic_price_only",
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 10.0,
            "keyword_overlap": ["wasser", "easyfill"],
            "ocr_price_eur": 1.38,
        }, {"grocery_hits": ["wasser"]})
        item = apply_strict_gate([base])[0]
        self.assertEqual(item["strict_disposition"], "strict_reject")
        self.assertEqual(item["strict_reason"], "nonfood_product_label")

    def test_strict_gate_downgrades_same_label_multiple_prices(self) -> None:
        raw = []
        for price in (5.95, 7.99):
            raw.append(assess_candidate({
                "page": 26,
                "product_name_raw": "Roséwein",
                "evidence_tier": "semantic_price_only",
                "psm_modes": [11, 12],
                "psm_support": 2,
                "semantic_score": 10.0,
                "keyword_overlap": ["rosewein", "wein"],
                "ocr_price_eur": price,
            }, {"grocery_hits": ["wein"]}))
        items = apply_strict_gate(raw)
        self.assertTrue(all(i["strict_disposition"] == "strict_review" for i in items))
        self.assertTrue(all(i["strict_reason"] == "ambiguous_same_label_multiple_prices" for i in items))

    def test_audit_v2_exposes_strict_shadow_gate(self) -> None:
        source = {
            "strategy": "full_grocery_ocr_dry_run",
            "db_write_performed": False,
            "dry_run_candidate_total": 2,
            "dry_run_candidates": [
                {"page": 10, "product_name_raw": "Hackfleisch", "evidence_tier": "math_verified", "psm_support": 2, "psm_modes": [11, 12], "semantic_score": 7, "keyword_overlap": ["hackfleisch"], "ocr_price_eur": 9.49, "math_expected_price_eur": 9.49, "db_write_eligible": False},
                {"page": 55, "product_name_raw": "Abtropfgewicht", "evidence_tier": "math_verified", "psm_support": 2, "psm_modes": [11, 12], "semantic_score": 7, "keyword_overlap": ["abtropfgewicht"], "ocr_price_eur": 1.29, "math_expected_price_eur": 1.29, "db_write_eligible": False},
            ],
            "pages": [
                {"page": 10, "selection": {"grocery_hits": ["milch"]}},
                {"page": 55, "selection": {"grocery_hits": ["wasser"]}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.json"
            src.write_text(json.dumps(source), encoding="utf-8")
            report = audit_candidate_precision(full_report_path=src, output_dir=root)
            self.assertEqual(report["schema_version"], 2)
            self.assertEqual(report["strict_ready_total"], 1)
            self.assertEqual(report["strict_review_total"], 1)
            self.assertTrue(report["gate"]["strict_ready_has_no_math_context_mismatch"])
            self.assertTrue(report["gate"]["strict_ready_all_nonwriting"])


if __name__ == "__main__":
    unittest.main()
