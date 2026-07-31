from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.lidl_corpus_import import (
    EXPECTED_PARSER_VERSION,
    build_offer,
    import_reconciled_safe,
    load_context,
    persist_safe_offers,
    register_source_snapshot,
    review_reason_codes,
    seed_review_rows,
    source_offer_id,
    validate_scan_contract,
)
from app.lidl_corpus_reconciliation import (
    semantic_digest,
    semantic_material_from_row,
)
from app.models import Base, OfferCandidateRecord, OfferReviewItem, OfferReviewRevision


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LidlCorpusImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.flyer = self.root / "flyer-key"
        self.scan = self.flyer / "scans" / "scan-0001"
        self.scan.mkdir(parents=True)

        source = {
            "dateTime": "2026-07-28T09:15:19+00:00",
            "self": "v4/flyer?flyer_identifier=test&region_id=21",
            "flyer": {
                "id": "flyer-official-id",
                "flyerUrlAbsolute": "https://www.lidl.de/l/prospekte/test/ar/21?_ab=1",
                "hiResPdfUrl": "https://assets.example.invalid/test.pdf",
                "offerStartDate": "2026-08-03",
                "offerEndDate": "2026-08-08",
                "pages": [
                    {
                        "number": 1,
                        "zoom": "https://img.example.invalid/page-1.jpg",
                    },
                    {
                        "number": 2,
                        "image": "https://img.example.invalid/page-2.jpg",
                    },
                ],
            },
        }
        (self.flyer / "source.json").write_text(
            json.dumps(source, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.flyer / "source.pdf").write_bytes(b"%PDF-test")
        self.raw_sha = _sha(self.flyer / "source.json")
        self.pdf_sha = _sha(self.flyer / "source.pdf")

        summary = {
            "schema_version": 1,
            "flyer_key": self.flyer.name,
            "scan": self.scan.name,
            "parser_version": EXPECTED_PARSER_VERSION,
            "parser_sha256": "a" * 64,
        }
        (self.scan / "summary.json").write_text(
            json.dumps(summary),
            encoding="utf-8",
        )

        self.fields = [
            "page",
            "product_name",
            "package_text",
            "price_eur",
            "regular_price_eur",
            "regular_price_source",
            "app_price_eur",
            "valid_from",
            "valid_until",
            "validity_source",
            "channel",
            "channel_source",
            "scope",
            "scope_source",
            "price_basis",
            "production_ready_shadow",
            "comparison_eligible_shadow",
            "r6_classification",
            "recovery_source",
            "warnings",
            "manual_reviewed",
            "manual_corrections",
        ]

        self.safe = {
            "page": "1",
            "product_name": "TEST Pasta",
            "package_text": "500 g",
            "price_eur": "1.29",
            "regular_price_eur": "1.99",
            "regular_price_source": "normalpreis",
            "app_price_eur": "0.99",
            "valid_from": "2026-08-03",
            "valid_until": "2026-08-08",
            "validity_source": "page_explicit_range",
            "channel": "physical_store",
            "channel_source": "no_local_online_only_marker",
            "scope": "in_scope",
            "scope_source": "title_target_taxonomy",
            "price_basis": "fixed_or_explicit",
            "production_ready_shadow": "True",
            "comparison_eligible_shadow": "True",
            "r6_classification": "normal_single",
            "recovery_source": "",
            "warnings": "[]",
            "manual_reviewed": "False",
            "manual_corrections": "[]",
        }
        self.review = dict(self.safe)
        self.review.update(
            {
                "page": "2",
                "product_name": "TEST Review",
                "price_eur": "2.22",
                "app_price_eur": "",
                "scope": "review",
                "scope_source": "no_owned_scope_evidence",
                "production_ready_shadow": "False",
                "warnings": '["scope_requires_review"]',
            }
        )
        self._write_tsv(self.scan / "target-rows.tsv", [self.safe, self.review])
        self._write_tsv(self.scan / "review-required.tsv", [self.review])

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def _write_tsv(self, path: Path, rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                delimiter="\t",
                fieldnames=self.fields,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)

    def _context(self):
        return load_context(
            flyer_dir=self.flyer,
            scan_name=self.scan.name,
            expected_raw_sha256=self.raw_sha,
            expected_pdf_sha256=self.pdf_sha,
        )

    def _snapshot(self, db: Session):
        return register_source_snapshot(
            db,
            flyer_dir=self.flyer,
            scan_name=self.scan.name,
            raw_root=self.root / "raw",
            db_raw_prefix=str(self.root / "raw"),
            expected_raw_sha256=self.raw_sha,
            expected_pdf_sha256=self.pdf_sha,
        )

    def _reconciliation_artifacts(self, rows: list[dict[str, str]]):
        entries = []
        for ordinal, row in enumerate(rows, start=1):
            material = semantic_material_from_row(row)
            digest = semantic_digest(material)
            if ordinal <= 134:
                source_id = (
                    f"lidl:corpus:{self.flyer.name}:scan-0003:"
                    f"r{ordinal:03d}:{digest[:12]}"
                )
                origin = "reused_exact_previous_corpus_identity"
                previous_offer_id = f"00000000-0000-0000-0000-{ordinal:012d}"
                previous_snapshot_id = "7fc04436-ad76-58ab-ab73-5bc7f6de7bbf"
            else:
                source_id = (
                    f"lidl:flyer:{self.flyer.name}:semantic-v2:{digest[:24]}"
                )
                origin = "new_semantic_v2_identity"
                previous_offer_id = None
                previous_snapshot_id = None
            entries.append(
                {
                    "ordinal": ordinal,
                    "source_offer_id": source_id,
                    "identity_origin": origin,
                    "previous_offer_candidate_id": previous_offer_id,
                    "previous_snapshot_id": previous_snapshot_id,
                    "semantic_digest_sha256": digest,
                    "semantic_material": material,
                }
            )
        plan = {
            "schema_version": 1,
            "workflow_version": "lidl-corpus-source-id-reconciliation-v1",
            "decision": "reuse_exact_previous_corpus_ids_and_allocate_semantic_v2_for_new_rows",
            "flyer_key": self.flyer.name,
            "scan": self.scan.name,
            "source": {"raw_sha256": self.raw_sha, "pdf_sha256": self.pdf_sha},
            "parser_version": EXPECTED_PARSER_VERSION,
            "parser_sha256": "a" * 64,
            "previous_corpus_snapshot": {
                "snapshot_id": "7fc04436-ad76-58ab-ab73-5bc7f6de7bbf",
                "raw_sha256": "a54d233f9ea5a44bf80655572d0c5d76797cb7fbf07842eeb7aabdacce9218d0",
                "rows": 134,
            },
            "protected_manual_publications": {
                "database_rows": 58,
                "distinct_source_offer_ids": 54,
                "revision_rows_collapsed_by_source_offer_id": 4,
                "source_offer_ids": [
                    f"manual-review-{index:032x}" for index in range(54)
                ],
            },
            "counts": {
                "planned_safe_rows": 204,
                "reused_exact_previous_corpus_ids": 134,
                "new_semantic_v2_ids": 70,
                "identity_collisions": 0,
                "manual_identity_collisions": 0,
            },
            "permissions": {
                "db_write": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "timer_install": False,
            },
            "entries": entries,
        }
        plan_path = self.root / "identity-plan.json"
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        plan_sha = _sha(plan_path)
        approval = {
            "schema_version": 1,
            "workflow_version": "lidl-controlled-safe-import-approval-v2-read-dedup",
            "decision": "approve_reconciled_safe_import",
            "flyer_key": self.flyer.name,
            "scan": self.scan.name,
            "source": {"raw_sha256": self.raw_sha, "pdf_sha256": self.pdf_sha},
            "identity_plan_sha256": plan_sha,
            "counts": {
                "new_source_snapshots": 1,
                "safe_offer_candidates": 204,
                "reused_previous_source_offer_ids": 134,
                "new_semantic_v2_source_offer_ids": 70,
                "protected_manual_database_rows": 58,
                "protected_manual_distinct_source_offer_ids": 54,
                "database_target_distinct_source_offer_ids": 258,

                "expected_visible_target_flyer_rows": 257,

                "completeness_rescue_precedence_suppressions": 1,
            },
            "permissions": {
                "db_write": True,
                "source_snapshot_write": True,
                "offer_candidate_write": True,
                "delete_existing_rows": False,
                "update_existing_rows": False,
                "review_seed": False,
                "auto_approve": False,
                "auto_publish": False,
                "systemd_change": False,
                "timer_install": False,
            },
        }
        approval_path = self.root / "import-approval.json"
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return plan_path, plan_sha, approval_path, _sha(approval_path)

    def test_validate_scan_exact_counts_and_parser_contract(self) -> None:
        report = validate_scan_contract(
            flyer_dir=self.flyer,
            scan_name=self.scan.name,
            expected_safe_count=1,
            expected_review_count=1,
            expected_raw_sha256=self.raw_sha,
            expected_pdf_sha256=self.pdf_sha,
        )
        self.assertEqual(report["safe_count"], 1)
        self.assertEqual(report["review_count"], 1)
        self.assertEqual(report["region"], "21")
        self.assertEqual(report["parser_version"], EXPECTED_PARSER_VERSION)

    def test_source_registration_is_content_addressed_and_idempotent(self) -> None:
        self.assertIsNotNone(self._context().collected_at.tzinfo)
        with Session(self.engine) as db:
            first = self._snapshot(db)
            second = self._snapshot(db)
            self.assertEqual(first.id, second.id)
            self.assertEqual(first.sha256, self.raw_sha)
            self.assertTrue(Path(first.snapshot_path).exists())
            self.assertEqual(
                db.scalar(select(func.count()).select_from(first.__class__)),
                1,
            )

    def test_source_registration_rejects_raw_sha_mismatch(self) -> None:
        with Session(self.engine) as db:
            with self.assertRaisesRegex(ValueError, "Raw source SHA mismatch"):
                register_source_snapshot(
                    db,
                    flyer_dir=self.flyer,
                    scan_name=self.scan.name,
                    raw_root=self.root / "raw",
                    db_raw_prefix=str(self.root / "raw"),
                    expected_raw_sha256="0" * 64,
                    expected_pdf_sha256=self.pdf_sha,
                )

    def test_safe_offer_has_stable_identity_and_page_provenance(self) -> None:
        with Session(self.engine) as db:
            snapshot = self._snapshot(db)
            context = self._context()
            offer = build_offer(
                row=self.safe,
                ordinal=1,
                context=context,
                snapshot=snapshot,
            )
            self.assertEqual(
                offer.source_offer_id,
                source_offer_id(
                    self.flyer.name,
                    self.scan.name,
                    1,
                    self.safe,
                ),
            )
            self.assertIsNone(offer.source_image_url)
            self.assertEqual(
                offer.raw_payload["page_image_url"],
                "https://img.example.invalid/page-1.jpg",
            )
            self.assertEqual(str(offer.price_eur), "1.29")
            self.assertEqual(str(offer.app_price_eur), "0.99")
            self.assertEqual(offer.app_valid_from, offer.valid_from)
            self.assertEqual(offer.app_valid_until, offer.valid_until)
            self.assertEqual(offer.source_store_external_id, "DE06664")
            self.assertEqual(offer.raw_payload["source_snapshot_sha256"], self.raw_sha)

    def test_review_reason_codes_are_stable_and_deduplicated(self) -> None:
        reasons = review_reason_codes(self.review)
        self.assertEqual(reasons, ["scope_requires_review"])

        variable = dict(self.safe)
        variable.update(
            {
                "scope": "in_scope",
                "price_basis": "variable_weight_example",
                "warnings": "[]",
            }
        )
        self.assertEqual(
            review_reason_codes(variable),
            ["variable_weight_requires_review"],
        )

    def test_review_seed_is_idempotent_and_uses_full_page_fallback(self) -> None:
        with Session(self.engine) as db:
            snapshot = self._snapshot(db)
            first = seed_review_rows(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                snapshot=snapshot,
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=1,
            )
            second = seed_review_rows(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                snapshot=snapshot,
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=1,
            )
            self.assertEqual(first[0].id, second[0].id)
            item = db.get(OfferReviewItem, first[0].id)
            self.assertEqual(item.provenance_json["crop_kind"], "full_page_fallback")
            self.assertEqual(
                item.provenance_json["crop_url"],
                "https://img.example.invalid/page-2.jpg",
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferReviewItem)),
                1,
            )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferReviewRevision)),
                1,
            )

    def test_safe_persistence_uses_generic_exact_snapshot_contract(self) -> None:
        with Session(self.engine) as db:
            snapshot = self._snapshot(db)
            written, offers = persist_safe_offers(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                snapshot=snapshot,
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=1,
            )
            replay, _ = persist_safe_offers(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                snapshot=snapshot,
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=1,
            )
            self.assertEqual(written, 1)
            self.assertEqual(replay, 0)
            self.assertEqual(len(offers), 1)
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(OfferCandidateRecord)
                    .where(OfferCandidateRecord.snapshot_id == snapshot.id)
                ),
                1,
            )

    def test_accepted_physical_file_is_preferred_for_safe_rows(self) -> None:
        self._write_tsv(self.scan / "accepted-physical.tsv", [self.safe])
        self._write_tsv(self.scan / "target-rows.tsv", [self.review])
        report = validate_scan_contract(
            flyer_dir=self.flyer,
            scan_name=self.scan.name,
            expected_safe_count=1,
            expected_review_count=1,
            expected_raw_sha256=self.raw_sha,
            expected_pdf_sha256=self.pdf_sha,
        )
        self.assertEqual(report["safe_count"], 1)

    def test_reconciled_safe_import_is_atomic_and_idempotent(self) -> None:
        rows = []
        for ordinal in range(1, 205):
            row = dict(self.safe)
            row.update(
                {
                    "product_name": f"TEST Product {ordinal}",
                    "price_eur": f"{1 + ordinal / 100:.2f}",
                    "app_price_eur": "",
                    "regular_price_eur": "",
                }
            )
            rows.append(row)
        self._write_tsv(self.scan / "accepted-physical.tsv", rows)
        plan_path, plan_sha, approval_path, approval_sha = (
            self._reconciliation_artifacts(rows)
        )
        with Session(self.engine) as db:
            first = import_reconciled_safe(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                raw_root=self.root / "raw",
                db_raw_prefix=str(self.root / "raw"),
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=204,
                identity_plan_path=plan_path,
                expected_identity_plan_sha256=plan_sha,
                approval_path=approval_path,
                expected_approval_sha256=approval_sha,
            )
            replay = import_reconciled_safe(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                raw_root=self.root / "raw",
                db_raw_prefix=str(self.root / "raw"),
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=204,
                identity_plan_path=plan_path,
                expected_identity_plan_sha256=plan_sha,
                approval_path=approval_path,
                expected_approval_sha256=approval_sha,
            )
            self.assertTrue(first["snapshot_created"])
            self.assertEqual(first["written"], 204)
            self.assertFalse(replay["snapshot_created"])
            self.assertEqual(replay["written"], 0)
            self.assertEqual(replay["snapshot_persisted"], 204)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
                204,
            )

    def test_completeness_rescue_seed_is_review_only_and_idempotent(self) -> None:
        from app.lidl_corpus_import import seed_completeness_rescue_rows

        artifact = self.flyer / "completeness-rescue.jsonl"
        record = {
            "schema_version": 1,
            "candidate_key": "p001-native-test",
            "flyer_key": self.flyer.name,
            "scan": self.scan.name,
            "parser_version": EXPECTED_PARSER_VERSION,
            "parser_sha256": "a" * 64,
            "source_raw_sha256": self.raw_sha,
            "source_pdf_sha256": self.pdf_sha,
            "page": 1,
            "evidence_kind": "native_geometry",
            "bbox": [10.0, 20.0, 100.0, 80.0],
            "evidence_text": "TEST Rescue",
            "product_name": "TEST Rescue",
            "package_text": "250 g",
            "price_eur": "2.49",
            "scope": "review",
            "channel": "physical_store",
            "confidence": 0.88,
            "requires_app": False,
            "review_required": True,
            "production_ready": False,
        }
        artifact.write_text(
            json.dumps(record, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        with Session(self.engine) as db:
            snapshot = self._snapshot(db)
            first = seed_completeness_rescue_rows(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                snapshot=snapshot,
                artifact_path=artifact,
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=1,
            )
            second = seed_completeness_rescue_rows(
                db,
                flyer_dir=self.flyer,
                scan_name=self.scan.name,
                snapshot=snapshot,
                artifact_path=artifact,
                expected_raw_sha256=self.raw_sha,
                expected_pdf_sha256=self.pdf_sha,
                expected_count=1,
            )
            self.assertEqual(first[0].id, second[0].id)
            item = db.get(OfferReviewItem, first[0].id)
            self.assertEqual(item.status, "pending")
            self.assertIn(
                "completeness_rescue_requires_review",
                item.reason_codes,
            )
            self.assertEqual(
                item.provenance_json["evidence_kind"],
                "native_geometry",
            )
            self.assertEqual(
                item.provenance_json["bbox"],
                [10.0, 20.0, 100.0, 80.0],
            )
            self.assertIs(item.original_payload["requires_app"], False)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
                0,
            )


if __name__ == "__main__":
    unittest.main()
