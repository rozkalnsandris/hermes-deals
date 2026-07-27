from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4, uuid5

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.lidl_offer_persistence import persist_lidl_strict_ready_offers
from app.models import Base, OfferCandidateRecord, SourceSnapshot


class LidlOfferPersistenceTest(unittest.TestCase):
    def _db(self) -> tuple[object, Session]:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        return engine, Session(engine)

    def _fixture(self, root: Path, *, evidence: str = "math_verified", psm_support: int = 2, expected: str = "9.49") -> tuple[Path, str]:
        raw = b'{"flyer":"immutable"}'
        sha = hashlib.sha256(raw).hexdigest()
        canonical = root / f"flyer-{sha}.json"
        canonical.write_bytes(raw)
        sid = uuid4()
        source_offer_id = "lidl:latest-leaflet-test:p10:abc"
        offer = {
            "source_chain": "lidl",
            "source_store_external_id": None,
            "source_store_name": "Lidl",
            "source_offer_id": source_offer_id,
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
            "snapshot_id": str(sid),
            "collected_at": "2026-07-23T21:19:36Z",
            "parser_version": "lidl-ocr-shadow-2b17",
            "raw_payload": {
                "db_write_eligible": False,
                "shadow_snapshot_id_is_synthetic": False,
                "source_snapshot_binding": True,
                "source_snapshot_id": str(sid),
                "source_snapshot_sha256": sha,
                "strict_disposition": "strict_ready",
                "evidence_tier": evidence,
                "psm_support": psm_support,
                "math_expected_price_eur": expected,
            },
        }
        report = {
            "strategy": "lidl_source_snapshot_provenance_binding",
            "recommendation": "lidl_real_snapshot_offer_shadow_valid",
            "offer_db_write_performed": False,
            "validation_error_total": 0,
            "source_snapshot_id": str(sid),
            "source_snapshot_sha256": sha,
            "real_snapshot_offer_candidate_total": 4,
            "mapped_candidates": [
                {"page": 10 + i, "db_write_eligible": False, "offer_candidate": dict(offer, source_offer_id=f"{source_offer_id}-{i}", product_name_raw=f"Hackfleisch {i}")}
                for i in range(4)
            ],
            "gate": {"a": True, "b": True},
        }
        path = root / "provenance.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path, str(sid)

    def _insert_snapshot(self, db: Session, root: Path, report_path: Path) -> SourceSnapshot:
        report = json.loads(report_path.read_text())
        sid = report["source_snapshot_id"]
        sha = report["source_snapshot_sha256"]
        path = root / f"flyer-{sha}.json"
        row = SourceSnapshot(
            id=sid,
            source_chain="lidl",
            source_url="https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=latest-leaflet-test",
            final_url=None,
            scope="current_week_flyer",
            collected_at="2026-07-23T21:19:36+00:00",
            http_status=200,
            elapsed_ms=None,
            content_type="application/json",
            content_bytes=path.stat().st_size,
            sha256=sha,
            snapshot_path=str(path),
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint="lidl_public_flyer_json_canonical",
            success=True,
            error=None,
        )
        # SQLAlchemy's Uuid accepts UUID, not string, on SQLite.
        from uuid import UUID
        row.id = UUID(sid)
        from datetime import datetime
        row.collected_at = datetime.fromisoformat("2026-07-23T21:19:36+00:00")
        db.add(row)
        db.commit()
        return row

    def test_first_write_persists_exactly_four_and_verifies_idempotence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root)
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                report = persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(report["rows_written_first_pass"], 4)
                self.assertEqual(report["rows_written_second_pass"], 0)
                self.assertEqual(report["lidl_rows_global_before"], 0)
                self.assertEqual(report["lidl_rows_global_after"], 4)
                self.assertEqual(report["recommendation"], "lidl_first_controlled_offer_write_valid")
                self.assertTrue(all(report["gate"].values()))
            finally:
                db.close(); engine.dispose()

    def test_record_ids_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, sid = self._fixture(root)
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                report = persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                first_source = json.loads(provenance.read_text())["mapped_candidates"][0]["offer_candidate"]["source_offer_id"]
                expected = str(uuid5(__import__('uuid').UUID(sid), first_source))
                self.assertIn(expected, report["record_ids_first_pass"])
                self.assertEqual(report["record_ids_first_pass"], report["record_ids_second_pass"])
            finally:
                db.close(); engine.dispose()

    def test_persisted_rows_are_promoted_not_shadow_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root)
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                rows = list(db.scalars(select(OfferCandidateRecord)).all())
                self.assertEqual(len(rows), 4)
                self.assertTrue(all(r.parser_version == "lidl-ocr-2b19" for r in rows))
                self.assertTrue(all(r.raw_payload["db_write_eligible"] is True for r in rows))
                self.assertTrue(all(r.raw_payload["db_write_performed"] is True for r in rows))
            finally:
                db.close(); engine.dispose()

    def test_non_math_verified_candidate_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root, evidence="semantic_price_only")
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                with self.assertRaisesRegex(ValueError, "controlled persistence validation failed"):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 0)
            finally:
                db.close(); engine.dispose()

    def test_single_psm_candidate_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root, psm_support=1)
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                with self.assertRaises(ValueError):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 0)
            finally:
                db.close(); engine.dispose()

    def test_math_mismatch_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root, expected="8.49")
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                with self.assertRaises(ValueError):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 0)
            finally:
                db.close(); engine.dispose()

    def test_existing_unexpected_rows_abort_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, sid = self._fixture(root)
            engine, db = self._db()
            try:
                snapshot = self._insert_snapshot(db, root, provenance)
                db.add(OfferCandidateRecord(
                    source_chain="lidl", product_name_raw="Unexpected", price_eur="1.00",
                    source_url="https://example.test", snapshot_id=snapshot.id,
                    collected_at=snapshot.collected_at, parser_version="other", raw_payload={},
                ))
                db.commit()
                with self.assertRaisesRegex(ValueError, "do not exactly match"):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 1)
            finally:
                db.close(); engine.dispose()

    def test_controlled_first_write_rejects_more_than_four_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root)
            data = json.loads(provenance.read_text())
            extra = json.loads(json.dumps(data["mapped_candidates"][0]))
            extra["offer_candidate"]["source_offer_id"] += "-extra"
            extra["offer_candidate"]["product_name_raw"] = "Extra"
            data["mapped_candidates"].append(extra)
            data["real_snapshot_offer_candidate_total"] = 5
            provenance.write_text(json.dumps(data), encoding="utf-8")
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                with self.assertRaisesRegex(ValueError, "requires exactly 4 mapped candidates"):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 0)
            finally:
                db.close(); engine.dispose()

    def test_missing_source_offer_id_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root)
            data = json.loads(provenance.read_text())
            data["mapped_candidates"][0]["offer_candidate"]["source_offer_id"] = None
            provenance.write_text(json.dumps(data), encoding="utf-8")
            engine, db = self._db()
            try:
                self._insert_snapshot(db, root, provenance)
                with self.assertRaisesRegex(ValueError, "controlled persistence validation failed"):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 0)
            finally:
                db.close(); engine.dispose()

    def test_snapshot_hash_change_aborts_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provenance, _ = self._fixture(root)
            engine, db = self._db()
            try:
                snapshot = self._insert_snapshot(db, root, provenance)
                Path(snapshot.snapshot_path).write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "hash changed"):
                    persist_lidl_strict_ready_offers(db=db, provenance_report_path=provenance, output_dir=root, raw_root=root)
                self.assertEqual(db.scalar(select(func.count()).select_from(OfferCandidateRecord)), 0)
            finally:
                db.close(); engine.dispose()


if __name__ == "__main__":
    unittest.main()
