from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.lidl_review_scope_repair import (
    SCOPE_CONTRACT,
    apply_scope_repair,
    load_scope_repair_manifest,
    rollback_scope_repair,
    validate_scope_repair,
)
from app.models import (
    Base,
    OfferCandidateRecord,
    OfferNormalization,
    OfferReviewItem,
    OfferReviewRevision,
    SourceSnapshot,
)


FLYER_KEY = "20260803-20260808-r21-test"
PLAN_SHA = "a" * 64


def _uid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"hermes-deals:test-scope-repair:{label}")


class LidlReviewScopeRepairTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        self.Session = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )
        Base.metadata.create_all(self.engine)
        self.temp = tempfile.TemporaryDirectory()
        self.manifest_path = Path(self.temp.name) / "repair-manifest.json"
        self.payload = self._manifest_payload()
        raw = (
            json.dumps(
                self.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        self.manifest_path.write_bytes(raw)
        self.manifest_sha = hashlib.sha256(raw).hexdigest()
        self.manifest = load_scope_repair_manifest(
            path=self.manifest_path,
            expected_sha256=self.manifest_sha,
        )
        self._seed_original_state()

    def tearDown(self) -> None:
        self.temp.cleanup()
        self.engine.dispose()

    def _rows(
        self,
        prefix: str,
        count: int,
        *,
        with_offer: bool,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for index in range(1, count + 1):
            label = f"{prefix}-{index:02d}"
            row = {
                "product_name": f"{prefix} product {index}",
                "review_item_id": str(_uid(f"review-{label}")),
                "source_row_key": f"scan:row-{label}",
            }
            if with_offer:
                row["published_offer_candidate_id"] = str(
                    _uid(f"offer-{label}")
                )
            rows.append(row)
        return rows

    def _manifest_payload(self) -> dict:
        return {
            "approved_in_scope_keep": self._rows(
                "keep", 6, with_offer=True
            ),
            "approved_out_of_scope_retract": self._rows(
                "retract", 7, with_offer=True
            ),
            "counts": {
                "approved_in_scope_keep": 6,
                "approved_out_of_scope_retract": 7,
                "pending_out_of_scope_cleanup": 38,
                "rejected_out_of_scope_keep_closed": 6,
            },
            "decision": "repair_required_after_manual_canary",
            "pending_out_of_scope_cleanup": self._rows(
                "pending", 38, with_offer=False
            ),
            "rejected_out_of_scope_keep_closed": self._rows(
                "rejected", 6, with_offer=False
            ),
            "scope_contract": SCOPE_CONTRACT,
        }

    def _snapshot(self, label: str) -> SourceSnapshot:
        return SourceSnapshot(
            id=_uid(f"snapshot-{label}"),
            source_chain="lidl",
            source_url=f"https://example.invalid/{label}",
            final_url=f"https://example.invalid/{label}",
            scope="manual_review_derived",
            collected_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
            http_status=200,
            elapsed_ms=0,
            content_type="application/json",
            content_bytes=1,
            sha256="b" * 64,
            snapshot_path=f"/immutable/{label}.json",
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint="manual_review_v1",
            success=True,
            error=None,
        )

    def _offer(
        self,
        *,
        row: dict[str, str],
        snapshot: SourceSnapshot,
    ) -> OfferCandidateRecord:
        return OfferCandidateRecord(
            id=UUID(row["published_offer_candidate_id"]),
            source_chain="lidl",
            source_store_external_id="DE06664",
            source_store_name="Test store",
            source_offer_id=f"manual-{row['review_item_id']}",
            product_name_raw=row["product_name"],
            brand_raw=None,
            description_raw=None,
            package_text_raw=None,
            price_eur=Decimal("1.99"),
            regular_price_eur=None,
            unit_price_eur=None,
            unit_label=None,
            pricing_mode=None,
            regular_unit_price_eur=None,
            example_weight_g=None,
            discount_percent=None,
            app_price_eur=None,
            requires_app=False,
            coupon_required=False,
            valid_from=None,
            valid_until=None,
            app_valid_from=None,
            app_valid_until=None,
            source_url="https://example.invalid/flyer",
            source_image_url=None,
            snapshot_id=snapshot.id,
            collected_at=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
            parser_version="manual-review-v1",
            raw_payload={
                "review_item_id": row["review_item_id"],
                "review_provenance": {
                    "review_seed_plan_sha256": PLAN_SHA,
                },
            },
        )

    def _item(
        self,
        *,
        row: dict[str, str],
        status: str,
        published: bool,
    ) -> OfferReviewItem:
        now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        return OfferReviewItem(
            id=UUID(row["review_item_id"]),
            source_chain="lidl",
            source_snapshot_id=None,
            source_flyer_key=FLYER_KEY,
            source_row_key=row["source_row_key"],
            page_number=1,
            parser_version="test",
            status=status,
            reason_codes=["scope_requires_review"],
            original_payload={
                "product_name": row["product_name"],
                "scope": "review",
                "channel": "physical_store",
            },
            corrected_payload=(
                {"scope": "in_scope"} if status == "approved" else {}
            ),
            provenance_json={
                "review_seed_plan_sha256": PLAN_SHA,
            },
            reviewer_note=None,
            published_offer_candidate_id=(
                UUID(row["published_offer_candidate_id"])
                if published
                else None
            ),
            created_at=now,
            updated_at=now,
            decided_at=(now if status in {"approved", "rejected"} else None),
        )

    def _seed_original_state(self) -> None:
        with self.Session.begin() as db:
            for group, status, published in (
                (self.payload["approved_in_scope_keep"], "approved", True),
                (
                    self.payload["approved_out_of_scope_retract"],
                    "approved",
                    True,
                ),
                (
                    self.payload["pending_out_of_scope_cleanup"],
                    "pending",
                    False,
                ),
                (
                    self.payload["rejected_out_of_scope_keep_closed"],
                    "rejected",
                    False,
                ),
            ):
                for row in group:
                    item = self._item(
                        row=row,
                        status=status,
                        published=published,
                    )
                    db.add(item)
                    db.add(
                        OfferReviewRevision(
                            id=_uid(f"seed-rev-{row['review_item_id']}"),
                            review_item_id=item.id,
                            revision_no=1,
                            action="seed",
                            payload_json={},
                            note=None,
                            created_at=datetime(
                                2026,
                                7,
                                31,
                                12,
                                0,
                                tzinfo=timezone.utc,
                            ),
                        )
                    )
                    if published:
                        snapshot = self._snapshot(row["review_item_id"])
                        db.add(snapshot)
                        db.add(self._offer(row=row, snapshot=snapshot))

    def test_exact_manifest_is_accepted(self) -> None:
        self.assertEqual(
            len(self.manifest.approved_out_of_scope_retract),
            7,
        )
        self.assertEqual(
            len(self.manifest.pending_out_of_scope_cleanup),
            38,
        )

    def test_manifest_sha_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            load_scope_repair_manifest(
                path=self.manifest_path,
                expected_sha256="0" * 64,
            )

    def test_manifest_scope_contract_drift_is_rejected(self) -> None:
        payload = dict(self.payload)
        payload["scope_contract"] = {"include": [], "exclude": []}
        path = Path(self.temp.name) / "bad.json"
        raw = json.dumps(payload, sort_keys=True).encode()
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "scope contract"):
            load_scope_repair_manifest(
                path=path,
                expected_sha256=hashlib.sha256(raw).hexdigest(),
            )

    def test_original_live_state_validates(self) -> None:
        with self.Session() as db:
            result = validate_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        self.assertEqual(result["state"], "original")
        self.assertEqual(result["out_of_scope_rows"], 51)

    def test_apply_is_exact_and_idempotent(self) -> None:
        with self.Session() as db:
            first = apply_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        self.assertEqual(first["newly_rejected"], 45)
        self.assertEqual(first["retracted_offers"], 7)
        self.assertFalse(first["reused"])

        with self.Session() as db:
            replay = apply_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["retracted_offers"], 0)

        with self.Session() as db:
            invalid_ids = [
                UUID(row["published_offer_candidate_id"])
                for row in self.payload["approved_out_of_scope_retract"]
            ]
            self.assertEqual(
                len(
                    list(
                        db.scalars(
                            select(OfferCandidateRecord).where(
                                OfferCandidateRecord.id.in_(invalid_ids)
                            )
                        ).all()
                    )
                ),
                0,
            )
            repair_revisions = list(
                db.scalars(
                    select(OfferReviewRevision).where(
                        OfferReviewRevision.payload_json[
                            "repair_manifest_sha256"
                        ].as_string()
                        == self.manifest_sha
                    )
                ).all()
            )
            self.assertEqual(len(repair_revisions), 45)

    def test_valid_drinks_are_preserved(self) -> None:
        with self.Session() as db:
            apply_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        with self.Session() as db:
            for row in self.payload["approved_in_scope_keep"]:
                item = db.get(
                    OfferReviewItem,
                    UUID(row["review_item_id"]),
                )
                self.assertEqual(item.status, "approved")
                self.assertEqual(
                    str(item.published_offer_candidate_id),
                    row["published_offer_candidate_id"],
                )
                self.assertIsNotNone(
                    db.get(
                        OfferCandidateRecord,
                        UUID(row["published_offer_candidate_id"]),
                    )
                )

    def test_rollback_restores_exact_original_state(self) -> None:
        with self.Session() as db:
            apply_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        with self.Session() as db:
            result = rollback_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        self.assertEqual(result["restored_review_items"], 45)
        self.assertEqual(result["restored_offers"], 7)
        with self.Session() as db:
            validation = validate_scope_repair(
                db,
                manifest=self.manifest,
                flyer_key=FLYER_KEY,
                plan_sha256=PLAN_SHA,
            )
        self.assertEqual(validation["state"], "original")

    def test_dependency_blocks_retraction(self) -> None:
        row = self.payload["approved_out_of_scope_retract"][0]
        with self.Session.begin() as db:
            db.add(
                OfferNormalization(
                    id=_uid("normalization"),
                    offer_candidate_id=UUID(
                        row["published_offer_candidate_id"]
                    ),
                    normalizer_version="test",
                    normalized_name="test",
                    normalized_brand=None,
                    item_quantity_value=None,
                    item_quantity_unit=None,
                    pack_count=None,
                    gtin14=None,
                    category_key=None,
                    evidence_json={},
                    created_at=datetime(
                        2026,
                        7,
                        31,
                        12,
                        0,
                        tzinfo=timezone.utc,
                    ),
                )
            )
        with self.Session() as db:
            with self.assertRaisesRegex(ValueError, "downstream dependencies"):
                apply_scope_repair(
                    db,
                    manifest=self.manifest,
                    flyer_key=FLYER_KEY,
                    plan_sha256=PLAN_SHA,
                )

    def test_live_identity_drift_is_rejected(self) -> None:
        row = self.payload["pending_out_of_scope_cleanup"][0]
        with self.Session.begin() as db:
            item = db.get(OfferReviewItem, UUID(row["review_item_id"]))
            item.source_row_key = "drifted"
        with self.Session() as db:
            with self.assertRaisesRegex(ValueError, "source-row mismatch"):
                validate_scope_repair(
                    db,
                    manifest=self.manifest,
                    flyer_key=FLYER_KEY,
                    plan_sha256=PLAN_SHA,
                )

    def test_cli_help_does_not_require_database_url(self) -> None:
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        backend_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.lidl_review_scope_repair",
                "--help",
            ],
            cwd=backend_root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        self.assertIn("validate", completed.stdout)
        self.assertIn("apply", completed.stdout)
        self.assertIn("rollback", completed.stdout)

    def test_legacy_review_seed_v1_is_disabled(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "lidl_corpus_import.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Legacy reconciled Review seed v1 is disabled",
            source,
        )


if __name__ == "__main__":
    unittest.main()
