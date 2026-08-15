from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.edeka_production_canary import (
    AUTHORIZATION_TYPE,
    CanaryEvidence,
    _build_snapshot,
    _canary_snapshot_id,
    _table_counts,
    execute_prepared_canary,
    load_plan,
)
from app.models import (
    Base,
    OfferCandidateRecord,
    OfferNormalization,
    SourceSnapshot,
)
from app.schemas import OfferCandidate, SourceChain


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "config" / "edeka-production-canary-v01.json"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
SHADOW_SNAPSHOT_ID = UUID("fb10cab0-3d9a-499d-8434-fd92bebb7c0e")


def _offer(plan_row: dict[str, object]) -> OfferCandidate:
    source_offer_id = str(plan_row["source_offer_id"])
    description = None
    image_url = None
    if source_offer_id == "059d39c8-69b8-4c99-9008-61341138ca0e":
        image_url = "https://offer-images.api.edeka/Papa_Joe_500ml.png"
    elif source_offer_id == "2e53629a-c206-44b0-9867-4922f2f1facd":
        description = "125 g Schale"
    elif source_offer_id == "0b6bcd44-9b9f-459c-bdce-f3e4fcf94edd":
        image_url = "https://offer-images.api.edeka/Kri_Kri_4x70g.png"
    else:
        raise AssertionError(source_offer_id)

    return OfferCandidate(
        source_chain=SourceChain.EDEKA,
        source_store_external_id="071897",
        source_store_name="EDEKA Patzer",
        source_offer_id=source_offer_id,
        product_name_raw=str(plan_row["product_name_raw"]),
        brand_raw=None,
        description_raw=description,
        package_text_raw=None,
        price_eur=Decimal(str(plan_row["price_eur"])),
        valid_from=date.fromisoformat(str(plan_row["valid_from"])),
        valid_until=date.fromisoformat(str(plan_row["valid_until"])),
        source_url=SOURCE_URL,
        source_image_url=image_url,
        snapshot_id=SHADOW_SNAPSHOT_ID,
        collected_at=COLLECTED_AT,
        parser_version="edeka-v1",
        raw_payload={
            "public_market_id": "071897",
            "internal_market_id": "587881",
            "dialog_id": str(plan_row["dialog_id"]),
            "description": description,
            "image_selection": (
                "product_candidate" if image_url else "none_or_logo_only"
            ),
        },
    )


def _evidence(plan) -> CanaryEvidence:
    manifest = {
        "source_chain": "edeka",
        "scope": "family_primary_edeka",
        "public_market_id": "071897",
        "internal_market_id": "587881",
        "store_name": "EDEKA Patzer",
        "source_url": SOURCE_URL,
        "final_url": SOURCE_URL,
        "snapshot_id": plan.source["shadow_snapshot_id"],
        "collected_at": COLLECTED_AT.isoformat(),
        "valid_from": plan.source["campaign_valid_from"],
        "valid_until": plan.source["campaign_valid_until"],
        "offer_count": plan.source["full_offer_count"],
        "raw_html_sha256": plan.source["raw_html_sha256"],
    }
    selected = [_offer(row) for row in plan.rows]
    return CanaryEvidence(
        manifest_path=Path("/retained/edeka-manifest.json"),
        raw_html_path=Path("/retained/edeka-source.html"),
        manifest=manifest,
        raw_html=b"retained-edeka-source",
        offers=selected,
        selected_offers=selected,
        normalization_report={},
    )


class EdekaProductionCanaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)")
        )
        self.db.execute(
            text(
                "INSERT INTO alembic_version(version_num) "
                "VALUES ('0007_comparison_family_pricing')"
            )
        )
        self.db.commit()
        self.plan = load_plan(PLAN_PATH)
        self.evidence = _evidence(self.plan)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _authorization_file(
        self,
        temporary: str,
        *,
        mode: str,
        baseline: dict[str, int],
        backup_verified: bool = True,
    ) -> Path:
        path = Path(temporary) / f"authorization-{mode}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "authorization_type": AUTHORIZATION_TYPE,
                    "production_apply_authorized": True,
                    "authorized_mode": mode,
                    "plan_id": self.plan.plan_id,
                    "plan_sha256": self.plan.sha256,
                    "manifest_sha256": self.plan.source["manifest_sha256"],
                    "rollback_backup_verified": backup_verified,
                    "baseline_counts": baseline,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def test_exact_repo_plan_contract_is_loaded(self) -> None:
        self.assertEqual(self.plan.payload["state"], "preparation_only")
        self.assertFalse(self.plan.payload["production_apply_authorized"])
        self.assertEqual(
            self.plan.expected_first_delta,
            {
                "source_snapshots": 1,
                "offer_candidates": 3,
                "offer_normalizations": 3,
                "product_match_candidates": 0,
                "offer_product_links": 0,
                "canonical_products": 0,
                "offer_review_items": 0,
                "offer_review_revisions": 0,
            },
        )
        self.assertTrue(
            all(value == 0 for value in self.plan.expected_replay_delta.values())
        )
        self.assertTrue(
            all(row["review_required"] is False for row in self.plan.rows)
        )

    def test_verify_empty_state_is_read_only(self) -> None:
        before = _table_counts(self.db)
        result = execute_prepared_canary(
            self.db,
            self.plan,
            self.evidence,
            mode="verify",
        )
        after = _table_counts(self.db)

        self.assertEqual(result["state"], "empty")
        self.assertFalse(result["writes_performed"])
        self.assertEqual(result["expected_next_delta"], self.plan.expected_first_delta)
        self.assertEqual(after, before)

    def test_apply_without_separate_owner_authorization_fails(self) -> None:
        before = _table_counts(self.db)
        with self.assertRaisesRegex(ValueError, "requires owner authorization"):
            execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="apply",
            )
        self.assertEqual(_table_counts(self.db), before)

    def test_apply_requires_verified_rollback_backup(self) -> None:
        baseline = _table_counts(self.db)
        with tempfile.TemporaryDirectory() as temporary:
            auth = self._authorization_file(
                temporary,
                mode="apply",
                baseline=baseline,
                backup_verified=False,
            )
            with self.assertRaisesRegex(
                ValueError,
                "rollback_backup_verified mismatch",
            ):
                execute_prepared_canary(
                    self.db,
                    self.plan,
                    self.evidence,
                    mode="apply",
                    authorization_path=auth,
                )
        self.assertEqual(_table_counts(self.db), baseline)

    def test_first_apply_is_exact_and_replay_is_zero_delta(self) -> None:
        baseline = _table_counts(self.db)
        with tempfile.TemporaryDirectory() as temporary:
            auth = self._authorization_file(
                temporary,
                mode="apply",
                baseline=baseline,
            )
            applied = execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="apply",
                authorization_path=auth,
            )
            replay = execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="apply",
                authorization_path=auth,
            )

        self.assertEqual(applied["state"], "applied")
        self.assertEqual(applied["delta"], self.plan.expected_first_delta)
        self.assertTrue(applied["writes_performed"])
        self.assertEqual(replay["state"], "replay_noop")
        self.assertEqual(replay["delta"], self.plan.expected_replay_delta)
        self.assertFalse(replay["writes_performed"])
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(SourceSnapshot)),
            1,
        )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
            3,
        )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(OfferNormalization)),
            3,
        )

    def test_partial_existing_state_fails_closed(self) -> None:
        self.db.add(_build_snapshot(self.plan, self.evidence))
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "partial persisted state"):
            execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="verify",
            )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(SourceSnapshot)),
            1,
        )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
            0,
        )

    def test_wrong_alembic_head_fails_before_write(self) -> None:
        self.db.execute(text("DELETE FROM alembic_version"))
        self.db.execute(
            text(
                "INSERT INTO alembic_version(version_num) "
                "VALUES ('0006_unit_basis_pricing')"
            )
        )
        self.db.commit()
        before = _table_counts(self.db)

        with self.assertRaisesRegex(ValueError, "Alembic head mismatch"):
            execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="verify",
            )
        self.assertEqual(_table_counts(self.db), before)

    def test_rollback_uses_separate_mode_bound_authorization(self) -> None:
        baseline = _table_counts(self.db)
        with tempfile.TemporaryDirectory() as temporary:
            apply_auth = self._authorization_file(
                temporary,
                mode="apply",
                baseline=baseline,
            )
            execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="apply",
                authorization_path=apply_auth,
            )

            with self.assertRaisesRegex(ValueError, "authorized_mode mismatch"):
                execute_prepared_canary(
                    self.db,
                    self.plan,
                    self.evidence,
                    mode="rollback",
                    authorization_path=apply_auth,
                )

            rollback_auth = self._authorization_file(
                temporary,
                mode="rollback",
                baseline=baseline,
            )
            rolled_back = execute_prepared_canary(
                self.db,
                self.plan,
                self.evidence,
                mode="rollback",
                authorization_path=rollback_auth,
            )

        self.assertEqual(rolled_back["state"], "rolled_back")
        self.assertTrue(rolled_back["writes_performed"])
        self.assertEqual(_table_counts(self.db), baseline)
        self.assertIsNone(self.db.get(SourceSnapshot, _canary_snapshot_id(self.plan)))

    def test_executor_source_has_no_network_acquisition_path(self) -> None:
        source = (
            REPO_ROOT / "backend" / "app" / "edeka_production_canary.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("httpx", source)
        self.assertNotIn("fetch_edeka_store_offers", source)
        self.assertNotIn("review_queue", source)
        self.assertNotIn("product_matching", source)


if __name__ == "__main__":
    unittest.main()
