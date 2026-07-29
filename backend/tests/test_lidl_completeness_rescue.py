from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.lidl_completeness_rescue import (
    load_rescue_artifact,
    rescue_reason_codes,
    rescue_row_key,
)


class LidlCompletenessRescueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = {
            "flyer_key": "flyer-test",
            "scan_name": "scan-0003",
            "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
            "parser_sha256": "a" * 64,
            "raw_sha256": "b" * 64,
            "pdf_sha256": "c" * 64,
            "valid_pages": {1, 16},
        }
        self.record = {
            "schema_version": 1,
            "candidate_key": "p001-native-001",
            "flyer_key": "flyer-test",
            "scan": "scan-0003",
            "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
            "parser_sha256": "a" * 64,
            "source_raw_sha256": "b" * 64,
            "source_pdf_sha256": "c" * 64,
            "page": 1,
            "evidence_kind": "native_geometry",
            "bbox": [10.0, 20.0, 110.0, 80.0],
            "evidence_text": "MAGNUM",
            "product_name": "LANGNESE Magnum",
            "package_text": None,
            "price_eur": None,
            "scope": "review",
            "channel": "physical_store",
            "confidence": 0.91,
            "review_required": True,
            "production_ready": False,
        }

    def _load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rescue.jsonl"
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
            return load_rescue_artifact(
                path,
                flyer_key=self.identity["flyer_key"],
                scan_name=self.identity["scan_name"],
                parser_version=self.identity["parser_version"],
                parser_sha256=self.identity["parser_sha256"],
                raw_sha256=self.identity["raw_sha256"],
                pdf_sha256=self.identity["pdf_sha256"],
                valid_pages=self.identity["valid_pages"],
                expected_count=len(rows),
            )

    def test_valid_record_gets_stable_digest_and_row_key(self) -> None:
        first = self._load([self.record])[0]
        second = self._load([self.record])[0]
        self.assertEqual(first["record_digest"], second["record_digest"])
        self.assertEqual(
            rescue_row_key("scan-0003", first),
            "scan-0003:rescue:p001-native-001",
        )

    def test_identity_mismatch_is_rejected(self) -> None:
        bad = dict(self.record)
        bad["source_pdf_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self._load([bad])

    def test_rescue_can_never_be_auto_production_ready(self) -> None:
        bad = dict(self.record)
        bad["production_ready"] = True
        with self.assertRaisesRegex(ValueError, "never be production_ready"):
            self._load([bad])

    def test_duplicate_candidate_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self._load([self.record, dict(self.record)])

    def test_targeted_ocr_and_missing_price_get_explicit_review_reasons(self) -> None:
        row = dict(self.record)
        row.update(
            {
                "candidate_key": "p001-ocr-001",
                "evidence_kind": "targeted_ocr",
                "scope": "in_scope",
            }
        )
        loaded = self._load([row])[0]
        self.assertEqual(
            rescue_reason_codes(loaded),
            [
                "completeness_rescue_requires_review",
                "completeness_targeted_ocr",
                "price_requires_review",
            ],
        )


if __name__ == "__main__":
    unittest.main()
