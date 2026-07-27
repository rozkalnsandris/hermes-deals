from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.lidl_source_provenance import bind_lidl_source_snapshot
from app.models import Base, OfferCandidateRecord, SourceSnapshot


class LidlSourceProvenanceTest(unittest.TestCase):
    def _fixture(self, root: Path, *, recorded_sha_override: str | None = None) -> Path:
        leaflet_key = "latest-leaflet-test"
        raw_payload = {
            "flyer": {
                "offerStartDate": "2026-07-20",
                "offerEndDate": "2026-07-25",
                "pages": [{"number": i} for i in range(1, 70)],
            }
        }
        raw_bytes = json.dumps(raw_payload, separators=(",", ":")).encode("utf-8")
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        raw_path = root / "raw-flyer.json"
        raw_path.write_bytes(raw_bytes)

        structure = {
            "strategy": "direct_public_leaflet_api_structure_probe",
            "generated_at": "2026-07-23T21:19:26+00:00",
            "flyer_probes": [
                {
                    "leaflet_key": leaflet_key,
                    "success": True,
                    "final_url": "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=latest-leaflet-test",
                    "attempts": [
                        {
                            "url": "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=latest-leaflet-test",
                            "status": 200,
                            "saved": {
                                "path": str(raw_path),
                                "sha256": recorded_sha_override or raw_sha,
                                "bytes": len(raw_bytes),
                                "content_type": "application/json",
                            },
                        }
                    ],
                }
            ],
        }
        structure_path = root / "structure.json"
        structure_path.write_text(json.dumps(structure), encoding="utf-8")

        page = {
            "strategy": "lidl_page_schema_deep_scan",
            "structure_report": str(structure_path),
            "payload_path": str(raw_path),
            "leaflet_key": leaflet_key,
        }
        page_path = root / "page.json"
        page_path.write_text(json.dumps(page), encoding="utf-8")

        full = {
            "strategy": "full_grocery_ocr_dry_run",
            "db_write_performed": False,
            "page_report": str(page_path),
            "leaflet_key": leaflet_key,
            "offer_start": "2026-07-20",
            "offer_end": "2026-07-25",
        }
        full_path = root / "full.json"
        full_path.write_text(json.dumps(full), encoding="utf-8")

        synthetic_id = "6b4c5320-1c7a-5148-9af7-1ce258b42dac"
        offer = {
            "source_chain": "lidl",
            "source_store_external_id": None,
            "source_store_name": "Lidl",
            "source_offer_id": "lidl:latest-leaflet-test:p10:abc",
            "product_name_raw": "Hackfleisch",
            "brand_raw": None,
            "description_raw": None,
            "package_text_raw": "Je 800 g",
            "price_eur": "9.49",
            "regular_price_eur": None,
            "unit_price_eur": "11.86",
            "unit_label": "kg",
            "discount_percent": None,
            "app_price_eur": None,
            "requires_app": False,
            "coupon_required": False,
            "valid_from": "2026-07-20",
            "valid_until": "2026-07-25",
            "source_url": "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=latest-leaflet-test",
            "source_image_url": "https://example.test/page-10.jpg",
            "snapshot_id": synthetic_id,
            "collected_at": "2026-07-23T21:19:36Z",
            "parser_version": "lidl-ocr-shadow-2b17",
            "raw_payload": {
                "shadow_mapping": True,
                "db_write_eligible": False,
                "shadow_snapshot_id_is_synthetic": True,
                "shadow_snapshot_id": synthetic_id,
            },
        }
        shadow = {
            "strategy": "lidl_offer_candidate_contract_shadow_mapping",
            "db_write_performed": False,
            "recommendation": "lidl_offer_candidate_shadow_contract_valid",
            "source_full_grocery_report": str(full_path),
            "source_leaflet_key": leaflet_key,
            "mapped_offer_candidate_total": 1,
            "mapped_candidates": [{"page": 10, "db_write_eligible": False, "offer_candidate": offer}],
        }
        shadow_path = root / "shadow.json"
        shadow_path.write_text(json.dumps(shadow), encoding="utf-8")
        return shadow_path

    def _db(self) -> tuple[object, Session]:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        return engine, Session(engine)

    def test_persists_real_snapshot_and_rebinds_offer_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = self._fixture(root)
            engine, db = self._db()
            try:
                report = bind_lidl_source_snapshot(
                    db=db,
                    shadow_report_path=shadow,
                    output_dir=root,
                    canonical_dir=root / "canonical",
                )
                self.assertTrue(report["source_snapshot_write_performed"])
                self.assertFalse(report["offer_db_write_performed"])
                self.assertEqual(report["real_snapshot_offer_candidate_total"], 1)
                self.assertEqual(report["validation_error_total"], 0)
                UUID(report["source_snapshot_id"])
                offer = report["mapped_candidates"][0]["offer_candidate"]
                self.assertEqual(offer["snapshot_id"], report["source_snapshot_id"])
                self.assertFalse(offer["raw_payload"]["shadow_snapshot_id_is_synthetic"])
                self.assertEqual(offer["raw_payload"]["source_snapshot_sha256"], report["source_snapshot_sha256"])
                self.assertEqual(report["recommendation"], "lidl_real_snapshot_offer_shadow_small_subset")
            finally:
                db.close()
                engine.dispose()

    def test_registration_is_idempotent_by_raw_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = self._fixture(root)
            engine, db = self._db()
            try:
                first = bind_lidl_source_snapshot(db=db, shadow_report_path=shadow, output_dir=root, canonical_dir=root / "canonical")
                second = bind_lidl_source_snapshot(db=db, shadow_report_path=shadow, output_dir=root, canonical_dir=root / "canonical")
                count = db.scalar(select(func.count()).select_from(SourceSnapshot))
                self.assertEqual(count, 1)
                self.assertEqual(first["source_snapshot_id"], second["source_snapshot_id"])
                self.assertTrue(second["source_snapshot_reused"])
                self.assertFalse(second["source_snapshot_write_performed"])
            finally:
                db.close()
                engine.dispose()

    def test_raw_sha_must_match_original_fetch_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = self._fixture(root, recorded_sha_override="0" * 64)
            engine, db = self._db()
            try:
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    bind_lidl_source_snapshot(db=db, shadow_report_path=shadow, output_dir=root, canonical_dir=root / "canonical")
                self.assertEqual(db.scalar(select(func.count()).select_from(SourceSnapshot)), 0)
            finally:
                db.close()
                engine.dispose()

    def test_canonical_snapshot_name_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = self._fixture(root)
            engine, db = self._db()
            try:
                report = bind_lidl_source_snapshot(db=db, shadow_report_path=shadow, output_dir=root, canonical_dir=root / "canonical")
                path = Path(report["canonical_snapshot_path"])
                self.assertTrue(path.exists())
                self.assertIn(report["source_snapshot_sha256"], path.name)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), report["source_snapshot_sha256"])
            finally:
                db.close()
                engine.dispose()

    def test_offer_table_remains_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = self._fixture(root)
            engine, db = self._db()
            try:
                bind_lidl_source_snapshot(db=db, shadow_report_path=shadow, output_dir=root, canonical_dir=root / "canonical")
                offers = db.scalar(select(func.count()).select_from(OfferCandidateRecord))
                snapshots = db.scalar(select(func.count()).select_from(SourceSnapshot))
                self.assertEqual(offers, 0)
                self.assertEqual(snapshots, 1)
            finally:
                db.close()
                engine.dispose()

    def test_all_binding_gates_are_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shadow = self._fixture(root)
            engine, db = self._db()
            try:
                report = bind_lidl_source_snapshot(db=db, shadow_report_path=shadow, output_dir=root, canonical_dir=root / "canonical")
                self.assertTrue(all(report["gate"].values()))
            finally:
                db.close()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
