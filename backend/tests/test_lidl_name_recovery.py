from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from app.lidl_ocr_inspector import (
    _dry_run_candidates,
    _recover_math_correction_product_name,
)
from app.lidl_offer_candidate_shadow import _candidate_to_offer


def _write_tsv(path: Path, lines: list[str]) -> None:
    header = [
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    ]
    rows = ["\t".join(header)]
    top = 100
    for line_num, line in enumerate(lines, 1):
        left = 100
        for word_num, word in enumerate(line.split(), 1):
            rows.append(
                "\t".join(
                    [
                        "5", "1", "1", "1", str(line_num), str(word_num),
                        str(left), str(top), "60", "25", "95.0", word,
                    ]
                )
            )
            left += 70
        top += 40
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _page_with_psm(root: Path, *, psm11: list[str], psm12: list[str]) -> dict:
    p11 = root / "psm11.tsv"
    p12 = root / "psm12.tsv"
    _write_tsv(p11, psm11)
    _write_tsv(p12, psm12)
    return {
        "success": True,
        "page": 23,
        "psm_results": {
            "11": {"tsv_path": str(p11)},
            "12": {"tsv_path": str(p12)},
        },
    }


def _penne_zone() -> dict:
    return {
        "automatic_candidate": True,
        "token": "0,59",
        "bbox": {"left": 1195, "top": 2145, "right": 1370, "bottom": 2231},
        "psm_modes": [11, 12],
        "psm_support": 2,
        "unit_price_math_verified": False,
        "unit_price_math_conflict": True,
        "unit_price_math_correction_candidate": True,
        "unit_price_math_correction_expected_price": 0.69,
        "best_semantic_pairing": {
            "text": "ENNE RIGATE a",
            "semantic_score": 8.66,
            "keyword_overlap": ["rigate"],
        },
        "unit_price_crosschecks": [
            {
                "expected_sale_price": 0.69,
                "package_text": "Je 500g",
                "unit_price": 1.38,
                "unit_kind": "kg",
                "label_overlap": ["rigate"],
                "unit_nearby": ["Je 500g", "Penne Rigate", "159°"],
            }
        ],
    }


class LidlNameRecoveryTest(unittest.TestCase):
    def test_dual_psm_exact_unit_math_name_recovers_penne(self) -> None:
        with TemporaryDirectory(prefix="lidl-name-recovery-") as tmp:
            page = _page_with_psm(
                Path(tmp),
                psm11=["Penne Rigate"],
                psm12=["Penne Rigate"],
            )
            recovery = _recover_math_correction_product_name(_penne_zone(), page)

        self.assertIsNotNone(recovery)
        assert recovery is not None
        self.assertEqual(recovery["original_semantic_product_name_raw"], "ENNE RIGATE a")
        self.assertEqual(recovery["recovered_product_name"], "Penne Rigate")
        self.assertEqual(recovery["product_name_recovery_psm_modes"], [11, 12])

    def test_name_present_in_only_one_psm_is_not_recovered(self) -> None:
        with TemporaryDirectory(prefix="lidl-name-recovery-") as tmp:
            page = _page_with_psm(
                Path(tmp),
                psm11=["Penne Rigate"],
                psm12=["Andere Pasta"],
            )
            recovery = _recover_math_correction_product_name(_penne_zone(), page)

        self.assertIsNone(recovery)

    def test_ambiguous_dual_psm_names_are_not_recovered(self) -> None:
        with TemporaryDirectory(prefix="lidl-name-recovery-") as tmp:
            page = _page_with_psm(
                Path(tmp),
                psm11=["Penne Rigate", "Pasta Rigate"],
                psm12=["Penne Rigate", "Pasta Rigate"],
            )
            zone = _penne_zone()
            zone["unit_price_crosschecks"][0]["unit_nearby"] = [
                "Penne Rigate",
                "Pasta Rigate",
            ]
            recovery = _recover_math_correction_product_name(zone, page)

        self.assertIsNone(recovery)

    def test_dry_run_and_shadow_preserve_original_and_recovered_names(self) -> None:
        with TemporaryDirectory(prefix="lidl-name-recovery-") as tmp:
            page = _page_with_psm(
                Path(tmp),
                psm11=["Penne Rigate"],
                psm12=["Penne Rigate"],
            )
            page["ensemble_credible_price_zones"] = [_penne_zone()]
            candidates = _dry_run_candidates([page])

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["product_name_raw"], "Penne Rigate")
        self.assertEqual(
            candidate["original_semantic_product_name_raw"],
            "ENNE RIGATE a",
        )
        self.assertEqual(candidate["recovered_product_name"], "Penne Rigate")
        self.assertEqual(
            candidate["product_name_recovery_reason"],
            "dual_psm_unit_math_label_overlap",
        )

        shadow_candidate = {
            **candidate,
            "product_name_clean": "Penne Rigate",
            "precision_disposition": "correction_review",
            "strict_disposition": "strict_ready",
            "strict_reasons": [
                "math_corrected_verified",
                "dual_psm",
                "unit_price_math_agreement",
                "correction_provenance_preserved",
            ],
            "evidence_tier": "math_corrected_verified",
            "corrected_price_verified": True,
            "effective_price_eur": 0.69,
        }

        offer = _candidate_to_offer(
            shadow_candidate,
            leaflet_key="phase2b39-test",
            full_report={
                "offer_start": "2026-07-20",
                "offer_end": "2026-07-25",
                "generated_at": "2026-07-23T21:19:36+00:00",
            },
            precision_report_path=Path("/tmp/precision.json"),
            page_urls={23: "https://example.test/page-23.jpg"},
            shadow_snapshot_id=UUID("00000000-0000-0000-0000-000000000139"),
        )

        payload = offer.model_dump(mode="json")
        raw = payload["raw_payload"]

        self.assertEqual(payload["product_name_raw"], "Penne Rigate")
        self.assertEqual(payload["price_eur"], "0.69")
        self.assertEqual(raw["ocr_product_name_raw"], "ENNE RIGATE a")
        self.assertEqual(raw["original_semantic_product_name_raw"], "ENNE RIGATE a")
        self.assertEqual(raw["recovered_product_name"], "Penne Rigate")
        self.assertEqual(
            raw["product_name_recovery_reason"],
            "dual_psm_unit_math_label_overlap",
        )
        self.assertEqual(raw["product_name_recovery_psm_modes"], [11, 12])


if __name__ == "__main__":
    unittest.main()
