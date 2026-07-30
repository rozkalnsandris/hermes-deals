from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.schemas import OfferCandidate
from app.lidl_offer_persistence import (
    _raw_payload_compatible,
    persist_lidl_strict_ready_offers,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot


class LidlPersistenceExpansionTest(unittest.TestCase):
    def _setup_db(self, root: Path) -> tuple[object, SourceSnapshot, str]:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)

        raw = root / "flyer.json"
        raw.write_bytes(b'{"fixture":"phase2b41"}')
        digest = sha256(raw.read_bytes()).hexdigest()

        snapshot = SourceSnapshot(
            id=uuid4(),
            source_chain="lidl",
            source_url="https://endpoints.leaflets.schwarz/v4/flyer?fixture=phase2b41",
            final_url="https://endpoints.leaflets.schwarz/v4/flyer?fixture=phase2b41",
            scope="current_week_flyer",
            collected_at=datetime(2026, 7, 23, 21, 19, 30, tzinfo=timezone.utc),
            http_status=200,
            elapsed_ms=10,
            content_type="application/json",
            content_bytes=raw.stat().st_size,
            sha256=digest,
            snapshot_path=str(raw),
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint="lidl_public_flyer_json_canonical",
            success=True,
            error=None,
        )

        with Session(engine) as db:
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

        return engine, snapshot, digest

    def _offer(
        self,
        *,
        snapshot: SourceSnapshot,
        snapshot_sha: str,
        name: str,
        source_offer_id: str,
        price: str,
        expected: str,
        evidence: str = "math_verified",
        corrected: bool = False,
    ) -> dict:
        raw = {
            "strict_disposition": "strict_ready",
            "evidence_tier": evidence,
            "psm_support": 2,
            "psm_modes": [11, 12],
            "math_expected_price_eur": float(expected),
            "source_snapshot_binding": True,
            "shadow_snapshot_id_is_synthetic": False,
            "source_snapshot_id": str(snapshot.id),
            "source_snapshot_sha256": snapshot_sha,
            "db_write_eligible": False,
        }

        if corrected:
            raw.update(
                {
                    "corrected_price_verified": True,
                    "ocr_price_eur": 0.59,
                    "proposed_corrected_price_eur": 0.69,
                    "effective_price_eur": 0.69,
                    "original_semantic_product_name_raw": "ENNE RIGATE a",
                    "recovered_product_name": "Penne Rigate",
                    "product_name_recovery_reason": "dual_psm_unit_math_label_overlap",
                    "product_name_recovery_psm_modes": [11, 12],
                }
            )

        offer = OfferCandidate(
            source_chain="lidl",
            source_store_external_id=None,
            source_store_name="Lidl",
            source_offer_id=source_offer_id,
            product_name_raw=name,
            brand_raw=None,
            description_raw=None,
            package_text_raw="Je 500g" if corrected else "fixture",
            price_eur=price,
            regular_price_eur=None,
            unit_price_eur="1.38" if corrected else expected,
            unit_label="kg",
            discount_percent=None,
            app_price_eur=None,
            requires_app=False,
            coupon_required=False,
            valid_from="2026-07-20",
            valid_until="2026-07-25",
            source_url="https://www.lidl.de/",
            source_image_url="https://example.test/page.jpg",
            snapshot_id=snapshot.id,
            collected_at="2026-07-23T21:19:36+00:00",
            parser_version="phase2b41c-fixture",
            raw_payload=raw,
        )
        return offer.model_dump(mode="json")

    def _approved_sets(self, snapshot: SourceSnapshot, digest: str) -> tuple[list[dict], list[dict]]:
        legacy = [
            self._offer(snapshot=snapshot, snapshot_sha=digest, name="Hackfleisch", source_offer_id="lidl:hack", price="9.49", expected="9.49"),
            self._offer(snapshot=snapshot, snapshot_sha=digest, name="Brühe", source_offer_id="lidl:bruehe", price="0.99", expected="0.99"),
            self._offer(snapshot=snapshot, snapshot_sha=digest, name="PESTO", source_offer_id="lidl:pesto", price="0.99", expected="0.99"),
            self._offer(snapshot=snapshot, snapshot_sha=digest, name="Tomaten", source_offer_id="lidl:tomaten", price="0.59", expected="0.59"),
        ]
        corrected = self._offer(
            snapshot=snapshot,
            snapshot_sha=digest,
            name="Penne Rigate",
            source_offer_id="lidl:penne",
            price="0.69",
            expected="0.69",
            evidence="math_corrected_verified",
            corrected=True,
        )
        return legacy, legacy + [corrected]

    def _provenance(self, root: Path, snapshot: SourceSnapshot, digest: str, offers: list[dict], name: str) -> Path:
        path = root / name
        report = {
            "strategy": "lidl_source_snapshot_provenance_binding",
            "recommendation": "lidl_real_snapshot_offer_shadow_valid",
            "offer_db_write_performed": False,
            "validation_error_total": 0,
            "gate": {"fixture_gate": True},
            "source_snapshot_id": str(snapshot.id),
            "source_snapshot_sha256": digest,
            "real_snapshot_offer_candidate_total": len(offers),
            "mapped_candidates": [
                {
                    "page": 23,
                    "db_write_eligible": False,
                    "offer_candidate": payload,
                }
                for payload in offers
            ],
        }
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path

    def test_four_to_five_exact_set_expansion_writes_only_missing_penne(self) -> None:
        with TemporaryDirectory(prefix="phase2b41c-expand-") as tmp:
            root = Path(tmp)
            engine, snapshot, digest = self._setup_db(root)
            four, five = self._approved_sets(snapshot, digest)
            p4 = self._provenance(root, snapshot, digest, four, "four.json")
            p5 = self._provenance(root, snapshot, digest, five, "five.json")

            with Session(engine) as db:
                first = persist_lidl_strict_ready_offers(
                    db=db, provenance_report_path=p4, output_dir=root, raw_root=root
                )
            self.assertEqual(first["rows_written_first_pass"], 4)

            with Session(engine) as db:
                expanded = persist_lidl_strict_ready_offers(
                    db=db, provenance_report_path=p5, output_dir=root, raw_root=root
                )

            self.assertEqual(expanded["lidl_rows_snapshot_before"], 4)
            self.assertEqual(expanded["rows_written_first_pass"], 1)
            self.assertEqual(expanded["rows_after_first_pass"], 5)
            self.assertEqual(expanded["rows_written_second_pass"], 0)
            self.assertEqual(
                expanded["recommendation"],
                "lidl_offer_persistence_exact_set_expansion_valid",
            )
            self.assertIn(
                "Penne Rigate",
                [p["product_name_raw"] for p in expanded["persisted_products"]],
            )

    def test_five_candidate_replay_is_idempotent(self) -> None:
        with TemporaryDirectory(prefix="phase2b41c-replay-") as tmp:
            root = Path(tmp)
            engine, snapshot, digest = self._setup_db(root)
            four, five = self._approved_sets(snapshot, digest)
            p4 = self._provenance(root, snapshot, digest, four, "four.json")
            p5 = self._provenance(root, snapshot, digest, five, "five.json")

            with Session(engine) as db:
                persist_lidl_strict_ready_offers(
                    db=db, provenance_report_path=p4, output_dir=root, raw_root=root
                )
            with Session(engine) as db:
                persist_lidl_strict_ready_offers(
                    db=db, provenance_report_path=p5, output_dir=root, raw_root=root
                )
            with Session(engine) as db:
                replay = persist_lidl_strict_ready_offers(
                    db=db, provenance_report_path=p5, output_dir=root, raw_root=root
                )

            self.assertEqual(replay["rows_written_first_pass"], 0)
            self.assertEqual(replay["rows_written_second_pass"], 0)
            self.assertEqual(replay["recommendation"], "lidl_offer_persistence_idempotent")

    def test_sixth_candidate_is_rejected_by_controlled_rollout_profile(self) -> None:
        with TemporaryDirectory(prefix="phase2b41c-six-") as tmp:
            root = Path(tmp)
            engine, snapshot, digest = self._setup_db(root)
            _, five = self._approved_sets(snapshot, digest)
            sixth = self._offer(
                snapshot=snapshot,
                snapshot_sha=digest,
                name="Extra",
                source_offer_id="lidl:extra",
                price="1.00",
                expected="1.00",
            )
            p6 = self._provenance(root, snapshot, digest, five + [sixth], "six.json")

            with Session(engine) as db:
                with self.assertRaisesRegex(ValueError, "Controlled first Lidl write requires exactly 4 mapped candidates"):
                    persist_lidl_strict_ready_offers(
                        db=db, provenance_report_path=p6, output_dir=root, raw_root=root
                    )

    def test_bad_corrected_provenance_is_rejected_before_write(self) -> None:
        with TemporaryDirectory(prefix="phase2b41c-bad-correction-") as tmp:
            root = Path(tmp)
            engine, snapshot, digest = self._setup_db(root)
            _, five = self._approved_sets(snapshot, digest)
            five[-1]["raw_payload"]["original_semantic_product_name_raw"] = None
            p5 = self._provenance(root, snapshot, digest, five, "bad-five.json")

            with Session(engine) as db:
                with self.assertRaisesRegex(ValueError, "Lidl controlled persistence validation failed for 1 candidate"):
                    persist_lidl_strict_ready_offers(
                        db=db, provenance_report_path=p5, output_dir=root, raw_root=root
                    )

            with Session(engine) as db:
                count = db.scalar(
                    select(func.count())
                    .select_from(OfferCandidateRecord)
                    .where(OfferCandidateRecord.source_chain == "lidl")
                )
            self.assertEqual(int(count or 0), 0)


    def test_legacy_raw_payload_allows_additive_enrichment_and_diagnostic_path(self) -> None:
        existing = {
            "evidence_tier": "math_verified",
            "ocr_price_eur": 9.49,
            "math_expected_price_eur": 9.49,
            "source_snapshot_id": "snapshot",
            "source_precision_report": "/old/precision.json",
        }
        approved = {
            **existing,
            "source_precision_report": "/tmp/new/precision.json",
            "effective_price_eur": 9.49,
            "corrected_price_verified": False,
            "original_semantic_product_name_raw": None,
            "recovered_product_name": None,
            "product_name_recovery_reason": None,
            "product_name_recovery_psm_modes": [],
        }
        self.assertTrue(_raw_payload_compatible(existing, approved))

    def test_legacy_raw_payload_rejects_material_evidence_change(self) -> None:
        existing = {
            "evidence_tier": "math_verified",
            "ocr_price_eur": 9.49,
            "math_expected_price_eur": 9.49,
            "source_snapshot_id": "snapshot",
        }
        approved = {
            **existing,
            "ocr_price_eur": 8.49,
            "effective_price_eur": 8.49,
        }
        self.assertFalse(_raw_payload_compatible(existing, approved))

if __name__ == "__main__":
    unittest.main()
