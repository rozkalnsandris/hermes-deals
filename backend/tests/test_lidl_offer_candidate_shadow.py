from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.lidl_offer_candidate_shadow import map_strict_ready_offer_candidates


class LidlOfferCandidateShadowTest(unittest.TestCase):
    def _write_reports(self, root: Path, candidates: list[dict]) -> Path:
        full = {
            "strategy": "full_grocery_ocr_dry_run",
            "db_write_performed": False,
            "generated_at": "2026-07-23T21:19:36+00:00",
            "leaflet_key": "latest-leaflet-test",
            "offer_start": "2026-07-20",
            "offer_end": "2026-07-25",
            "pages": [
                {
                    "page": 10,
                    "success": True,
                    "download": {"final_url": "https://example.test/page-10.jpg"},
                },
                {
                    "page": 23,
                    "success": True,
                    "download": {"final_url": "https://example.test/page-23.jpg"},
                },
            ],
        }
        full_path = root / "full.json"
        full_path.write_text(json.dumps(full), encoding="utf-8")
        precision = {
            "strategy": "lidl_full_grocery_candidate_precision_audit",
            "db_write_performed": False,
            "source_report": str(full_path),
            "source_leaflet_key": "latest-leaflet-test",
            "source_offer_start": "2026-07-20",
            "source_offer_end": "2026-07-25",
            "strict_ready_total": sum(c.get("strict_disposition") == "strict_ready" for c in candidates),
            "candidates": candidates,
        }
        precision_path = root / "precision.json"
        precision_path.write_text(json.dumps(precision), encoding="utf-8")
        return precision_path

    @staticmethod
    def _ready(page: int = 10, name: str = "Hackfleisch", price: float = 9.49) -> dict:
        return {
            "page": page,
            "product_name_raw": name,
            "product_name_clean": name,
            "ocr_price_eur": price,
            "math_expected_price_eur": price,
            "proposed_corrected_price_eur": None,
            "evidence_tier": "math_verified",
            "precision_disposition": "precision_ready",
            "strict_disposition": "strict_ready",
            "strict_reasons": ["math_verified"],
            "psm_modes": [11, 12],
            "psm_support": 2,
            "semantic_score": 8.0,
            "keyword_overlap": [name.lower()],
            "package_text": "Je 800 g",
            "unit_price": 11.86,
            "unit_kind": "kg",
            "bbox": {"left": 100, "top": 200, "right": 300, "bottom": 350},
            "db_write_eligible": False,
        }

    def test_maps_strict_ready_to_valid_offer_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            precision = self._write_reports(root, [self._ready()])
            report = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            self.assertEqual(report["mapped_offer_candidate_total"], 1)
            self.assertEqual(report["validation_error_total"], 0)
            offer = report["mapped_candidates"][0]["offer_candidate"]
            self.assertEqual(offer["source_chain"], "lidl")
            self.assertEqual(offer["product_name_raw"], "Hackfleisch")
            self.assertEqual(offer["price_eur"], "9.49")
            self.assertEqual(offer["unit_price_eur"], "11.86")
            self.assertEqual(offer["unit_label"], "kg")
            self.assertEqual(offer["valid_from"], "2026-07-20")
            self.assertEqual(offer["valid_until"], "2026-07-25")

    def test_non_strict_ready_is_not_mapped(self) -> None:
        review = self._ready()
        review["strict_disposition"] = "strict_review"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            precision = self._write_reports(root, [review])
            report = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            self.assertEqual(report["mapped_offer_candidate_total"], 0)
            self.assertEqual(report["source_strict_ready_total"], 0)

    def test_correction_review_never_becomes_shadow_offer(self) -> None:
        correction = self._ready(page=23, name="Penne Rigate", price=0.59)
        correction.update({
            "evidence_tier": "math_correction_review",
            "strict_disposition": "strict_review",
            "proposed_corrected_price_eur": 0.69,
        })
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            precision = self._write_reports(root, [correction])
            report = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            self.assertEqual(report["mapped_offer_candidate_total"], 0)

    def test_source_offer_id_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            precision = self._write_reports(root, [self._ready()])
            first = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            second = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            first_id = first["mapped_candidates"][0]["offer_candidate"]["source_offer_id"]
            second_id = second["mapped_candidates"][0]["offer_candidate"]["source_offer_id"]
            self.assertEqual(first_id, second_id)

    def test_shadow_mapping_preserves_nonwriting_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            precision = self._write_reports(root, [self._ready()])
            report = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            entry = report["mapped_candidates"][0]
            raw = entry["offer_candidate"]["raw_payload"]
            self.assertFalse(report["db_write_performed"])
            self.assertFalse(entry["db_write_eligible"])
            self.assertFalse(raw["db_write_eligible"])
            self.assertTrue(raw["shadow_mapping"])
            self.assertTrue(raw["shadow_snapshot_id_is_synthetic"])

    def test_shadow_mapping_uses_page_image_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            precision = self._write_reports(root, [self._ready(page=23, name="Pesto", price=0.99)])
            report = map_strict_ready_offer_candidates(precision_report_path=precision, output_dir=root)
            offer = report["mapped_candidates"][0]["offer_candidate"]
            self.assertEqual(offer["source_image_url"], "https://example.test/page-23.jpg")
            self.assertIn("flyer_identifier=latest-leaflet-test", offer["source_url"])


if __name__ == "__main__":
    unittest.main()
