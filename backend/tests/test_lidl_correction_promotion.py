from pathlib import Path
import unittest
from uuid import UUID

from app.lidl_candidate_precision import apply_strict_gate, assess_candidate
from app.lidl_offer_candidate_shadow import _candidate_to_offer


class LidlCorrectionPromotionTest(unittest.TestCase):
    def _high_confidence_correction(self, *, psm_support: int = 2) -> dict:
        candidate = {
            "page": 23,
            "product_name_raw": "ENNE RIGATE a",
            "evidence_tier": "math_correction_review",
            "psm_support": psm_support,
            "psm_modes": [11, 12] if psm_support >= 2 else [12],
            "semantic_score": 8.66,
            "keyword_overlap": ["rigate"],
            "ocr_price_eur": 0.59,
            "math_expected_price_eur": 0.69,
            "proposed_corrected_price_eur": 0.69,
            "package_text": "Je 500g",
            "unit_price": 1.38,
            "unit_kind": "kg",
            "bbox": {"left": 1195, "top": 2145, "right": 1370, "bottom": 2231},
        }
        return assess_candidate(candidate, {"grocery_hits": ["wein"]})

    def test_high_confidence_math_correction_is_strict_ready_nonwriting(self) -> None:
        item = apply_strict_gate([self._high_confidence_correction()])[0]
        self.assertEqual(item["precision_disposition"], "correction_review")
        self.assertEqual(item["strict_disposition"], "strict_ready")
        self.assertIsNone(item["strict_reason"])
        self.assertEqual(item["evidence_tier"], "math_corrected_verified")
        self.assertIs(item["corrected_price_verified"], True)
        self.assertEqual(item["effective_price_eur"], 0.69)
        self.assertEqual(item["ocr_price_eur"], 0.59)
        self.assertIs(item["db_write_eligible"], False)

    def test_single_psm_math_correction_stays_review_only(self) -> None:
        item = apply_strict_gate([self._high_confidence_correction(psm_support=1)])[0]
        self.assertEqual(item["strict_disposition"], "strict_review")
        self.assertEqual(item["strict_reason"], "math_correction_review")
        self.assertEqual(item["evidence_tier"], "math_correction_review")
        self.assertIsNot(item.get("corrected_price_verified"), True)

    def test_shadow_materializes_corrected_price_and_preserves_ocr_provenance(self) -> None:
        candidate = apply_strict_gate([self._high_confidence_correction()])[0]

        offer = _candidate_to_offer(
            candidate,
            leaflet_key="phase2b37a-test",
            full_report={
                "offer_start": "2026-07-20",
                "offer_end": "2026-07-25",
                "generated_at": "2026-07-23T21:19:36+00:00",
            },
            precision_report_path=Path("/tmp/precision.json"),
            page_urls={23: "https://example.test/page-23.jpg"},
            shadow_snapshot_id=UUID("00000000-0000-0000-0000-000000000123"),
        )

        payload = offer.model_dump(mode="json")
        self.assertEqual(payload["price_eur"], "0.69")
        self.assertEqual(payload["raw_payload"]["ocr_price_eur"], 0.59)
        self.assertEqual(payload["raw_payload"]["proposed_corrected_price_eur"], 0.69)
        self.assertEqual(payload["raw_payload"]["math_expected_price_eur"], 0.69)
        self.assertEqual(payload["raw_payload"]["effective_price_eur"], 0.69)
        self.assertIs(payload["raw_payload"]["corrected_price_verified"], True)
        self.assertEqual(payload["raw_payload"]["evidence_tier"], "math_corrected_verified")
        self.assertIs(payload["raw_payload"]["db_write_eligible"], False)

    def test_math_verified_shadow_price_behavior_is_unchanged(self) -> None:
        candidate = {
            "page": 10,
            "product_name_raw": "Hackfleisch",
            "product_name_clean": "Hackfleisch",
            "ocr_price_eur": 9.49,
            "math_expected_price_eur": 9.49,
            "proposed_corrected_price_eur": None,
            "evidence_tier": "math_verified",
            "precision_disposition": "precision_ready",
            "strict_disposition": "strict_ready",
            "strict_reasons": ["math_verified"],
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 7.0,
            "keyword_overlap": ["hackfleisch"],
            "package_text": "Je 800 g",
            "unit_price": 11.86,
            "unit_kind": "kg",
            "bbox": {"left": 10, "top": 10, "right": 100, "bottom": 100},
        }

        offer = _candidate_to_offer(
            candidate,
            leaflet_key="phase2b37a-test",
            full_report={
                "offer_start": "2026-07-20",
                "offer_end": "2026-07-25",
                "generated_at": "2026-07-23T21:19:36+00:00",
            },
            precision_report_path=Path("/tmp/precision.json"),
            page_urls={10: "https://example.test/page-10.jpg"},
            shadow_snapshot_id=UUID("00000000-0000-0000-0000-000000000124"),
        )

        payload = offer.model_dump(mode="json")
        self.assertEqual(payload["price_eur"], "9.49")
        self.assertEqual(payload["raw_payload"]["ocr_price_eur"], 9.49)
        self.assertIs(payload["raw_payload"]["corrected_price_verified"], False)


if __name__ == "__main__":
    unittest.main()
