from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import hashlib
from pathlib import Path
import unittest
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.lidl_v631_semantic_persistence import (
    LidlSemanticPersistenceError,
    apply_lidl_v631_semantic_persistence_plan,
    build_lidl_v631_semantic_persistence_plan,
    canonical_json_bytes,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "lidl"
    / "issue_615_reviewed_canary_landliebe.json"
)
RECEIPT_SHA256 = "b5670a4cd6cb2fe9c7d31ef3dd1a330e67f636d6a2912a42a00aad89469bb5c9"
ROW_KEY = "dc83d8fb7156f7e7e48eccb01f0ade4c744308c69c4caad9f3afee53305a4669"
ROW_BINDING = "fbe1cc5767b6eae416393d0f701e839ab7b2edf557cee9ac3f257a9b9612d2fe"


def source_binding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "family": "aktionsprospekt-10-08-2026-15-08-2026-71933b",
        "source_pdf_sha256": "ce84a4996f5c709620b8becc44c4e2a23e23d24b28694679903490efc91ce728",
        "source_raw_sha256": "12322c9989ea4038c7fb1e6d11e2728b6090e44958619b8cf4e5b22792f098fc",
        "scan_tree_sha256": "dd4ef887a72d6942bbade1adf8f2e2e29c229675c8c28bb1f0b41c1082d4f4c1",
        "review_profile_sha256": "83befbe6740bda5e55d83b52a69ccbceb0dea62be329d93a2b3c740fe67fe03e",
        "semantic_tree_sha256": "6138e424f38c27fd7577c8fa09c0686e433b6c7b39771834e5a3d1c062050936",
        "semantic_manifest_sha256": "b3250f1ca41029b5762419d97005b9ef28c6ccee10c303c7d696020fa74f9063",
        "semantic_rows_sha256": "a719be8d7371df3edd3a951287f78771937d79b18d671a9793c3c45c7e8115de",
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
        "reviewed_canary_receipt_sha256": RECEIPT_SHA256,
        "source_url": (
            "https://endpoints.leaflets.schwarz/v4/flyer"
            "?flyer_identifier=aktionsprospekt-10-08-2026-15-08-2026-71933b"
        ),
        "source_collected_at": "2026-08-11T11:16:15+00:00",
        "source_content_bytes": 1024,
        "snapshot_path": (
            "/home/andris/hermes-deals-lidl-corpus/flyers/"
            "aktionsprospekt-10-08-2026-15-08-2026-71933b/source.json"
        ),
    }


def semantic_row() -> dict[str, object]:
    return {
        "semantic_row_key": ROW_KEY,
        "page": 19,
        "product_name": "LANDLIEBE Butter",
        "package_text": "250 g",
        "price_eur": "1.39",
        "regular_price_eur": "2.69",
        "regular_price_source": "uvp",
        "pricing_mode": "fixed_package",
        "price_basis": "fixed_or_explicit",
        "channel": "physical_store",
        "scope": "in_scope",
        "weekly_partition": "production_ready",
        "weekly_eligibility_state": "production_ready",
        "production_ready_shadow": True,
        "parser_production_ready_shadow": True,
        "comparison_eligible_shadow": True,
        "semantic_gate_reasons": [],
        "card_bbox": [
            139.2440948486328,
            97.16217041015625,
            307.3262023925781,
            285.38002014160156,
        ],
        "app_price_eur": None,
        "requires_app": False,
        "coupon_required": False,
        "coupon_signal": False,
        "multi_buy_signal": False,
        "warnings": [],
        "rejection_reasons": [],
    }


def _auth(plan: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "decision": "approve_lidl_v631_one_row_canary_apply",
        "scope": "exact_one_row_production_db_canary",
        "payload_fingerprint": plan["payload_fingerprint"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "reviewed_canary_receipt_sha256": RECEIPT_SHA256,
        "semantic_row_key": ROW_KEY,
        "source_offer_id": plan["offer_candidate"]["source_offer_id"],
        "permissions": {
            "production_database_write": True,
            "max_source_snapshot_writes": 1,
            "max_offer_candidate_writes": 1,
            "review_write": False,
            "production_publish": False,
            "production_deploy": False,
            "corpus_write": False,
            "source_replacement": False,
            "systemd_change": False,
            "scheduler_change": False,
        },
    }


class LidlV631SemanticPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.receipt = FIXTURE.read_bytes()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def plan(
        self,
        *,
        rows: list[dict[str, object]] | None = None,
        binding: dict[str, object] | None = None,
        row_binding: str = ROW_BINDING,
        receipt: bytes | None = None,
    ) -> dict[str, object]:
        return build_lidl_v631_semantic_persistence_plan(
            db=self.db,
            reviewed_receipt_bytes=self.receipt if receipt is None else receipt,
            semantic_rows=rows or [semantic_row()],
            row_binding_sha256=row_binding,
            source_binding=binding or source_binding(),
        )

    def test_fixture_is_exact_reviewed_canary_receipt(self) -> None:
        self.assertEqual(hashlib.sha256(self.receipt).hexdigest(), RECEIPT_SHA256)

    def test_exact_landliebe_fixture_builds_deterministic_create_plan(self) -> None:
        first = self.plan()
        second = self.plan()
        self.assertEqual(first["result"], "READY_TO_CREATE")
        self.assertEqual(first["source_snapshot_action"], "CREATE")
        self.assertEqual(first["offer_candidate_action"], "CREATE")
        self.assertEqual(
            first["expected_deltas"],
            {
                "first_apply": {"source_snapshots": 1, "offer_candidates": 1},
                "replay": {"source_snapshots": 0, "offer_candidates": 0},
            },
        )
        self.assertEqual(first["bindings"]["semantic_row_key"], ROW_KEY)
        self.assertEqual(
            first["offer_candidate"]["source_offer_id"],
            (
                "lidl:v631:aktionsprospekt-10-08-2026-15-08-2026-71933b:"
                + ROW_KEY
            ),
        )
        self.assertEqual(first["offer_candidate"]["payload"]["product_name_raw"], "LANDLIEBE Butter")
        self.assertEqual(first["offer_candidate"]["payload"]["package_text_raw"], "250 g")
        self.assertEqual(first["offer_candidate"]["payload"]["price_eur"], "1.39")
        self.assertEqual(first["offer_candidate"]["payload"]["regular_price_eur"], "2.69")
        self.assertEqual(first["offer_candidate"]["payload"]["valid_from"], "2026-08-10")
        self.assertEqual(first["offer_candidate"]["payload"]["valid_until"], "2026-08-15")
        self.assertFalse(first["database_write"])
        self.assertEqual(
            canonical_json_bytes(first),
            canonical_json_bytes(second),
        )

    def test_planner_is_read_only(self) -> None:
        self.plan()
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(SourceSnapshot)),
            0,
        )
        self.assertEqual(
            self.db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
            0,
        )

    def test_wrong_receipt_or_binding_fails_closed(self) -> None:
        bad_receipt = self.receipt + b" "
        with self.assertRaisesRegex(
            LidlSemanticPersistenceError,
            "receipt SHA-256 mismatch",
        ):
            self.plan(receipt=bad_receipt)

        with self.assertRaisesRegex(
            LidlSemanticPersistenceError,
            "row binding SHA-256 mismatch",
        ):
            self.plan(row_binding="0" * 64)

        for field, value in (
            ("family", "other-family"),
            ("source_pdf_sha256", "0" * 64),
            ("source_raw_sha256", "1" * 64),
            ("review_profile_sha256", "2" * 64),
            ("semantic_tree_sha256", "3" * 64),
            ("semantic_rows_sha256", "4" * 64),
        ):
            with self.subTest(field=field):
                binding = source_binding()
                binding[field] = value
                with self.assertRaisesRegex(
                    LidlSemanticPersistenceError,
                    "differs from reviewed receipt",
                ):
                    self.plan(binding=binding)

    def test_altered_reviewed_material_fails_closed(self) -> None:
        variants = (
            ("product_name", "LANDLIEBE Butter extra"),
            ("package_text", "500 g"),
            ("price_eur", "1.49"),
            ("regular_price_eur", "2.79"),
        )
        for field, value in variants:
            with self.subTest(field=field):
                row = semantic_row()
                row[field] = value
                with self.assertRaisesRegex(
                    LidlSemanticPersistenceError,
                    "differs from reviewed receipt",
                ):
                    self.plan(rows=[row])

        binding = source_binding()
        binding["valid_until"] = "2026-08-16"
        with self.assertRaisesRegex(
            LidlSemanticPersistenceError,
            "differs from reviewed receipt",
        ):
            self.plan(binding=binding)

    def test_more_than_one_row_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            LidlSemanticPersistenceError,
            "exactly one semantic row",
        ):
            self.plan(rows=[semantic_row(), deepcopy(semantic_row())])

    def test_simple_path_rejects_variable_app_coupon_and_multi_buy_rows(self) -> None:
        cases = []
        variable = semantic_row()
        variable["pricing_mode"] = "example_total_plus_unit"
        variable["price_basis"] = "variable_weight_example"
        cases.append(variable)

        app = semantic_row()
        app["app_price_eur"] = "1.29"
        cases.append(app)

        coupon = semantic_row()
        coupon["coupon_required"] = True
        cases.append(coupon)

        multi = semantic_row()
        multi["multi_buy_signal"] = True
        cases.append(multi)

        for row in cases:
            with self.subTest(row=row):
                with self.assertRaises(LidlSemanticPersistenceError):
                    self.plan(rows=[row])

    def _seed_exact_plan(self, plan: dict[str, object]) -> None:
        snapshot = dict(plan["source_snapshot"])
        snapshot["id"] = UUID(snapshot["id"])
        snapshot["collected_at"] = datetime.fromisoformat(snapshot["collected_at"])
        self.db.add(SourceSnapshot(**snapshot))

        offer = dict(plan["offer_candidate"]["payload"])
        offer["snapshot_id"] = UUID(offer["snapshot_id"])
        offer["collected_at"] = datetime.fromisoformat(offer["collected_at"])
        for key in ("valid_from", "valid_until"):
            offer[key] = date.fromisoformat(offer[key])
        for key in (
            "price_eur",
            "regular_price_eur",
            "unit_price_eur",
            "regular_unit_price_eur",
            "example_weight_g",
            "app_price_eur",
        ):
            if offer.get(key) is not None:
                offer[key] = Decimal(offer[key])
        self.db.add(
            OfferCandidateRecord(
                id=UUID(plan["offer_candidate"]["id"]),
                **offer,
            )
        )
        self.db.commit()

    def test_existing_identical_source_and_offer_are_noop(self) -> None:
        create_plan = self.plan()
        self._seed_exact_plan(create_plan)
        replay = self.plan()
        self.assertEqual(replay["result"], "NO_OP_IDENTICAL")
        self.assertEqual(replay["source_snapshot_action"], "NO_OP_IDENTICAL")
        self.assertEqual(replay["offer_candidate_action"], "NO_OP_IDENTICAL")
        self.assertEqual(
            replay["expected_deltas"]["first_apply"],
            {"source_snapshots": 0, "offer_candidates": 0},
        )
        self.assertEqual(
            replay["payload_fingerprint"],
            create_plan["payload_fingerprint"],
        )

    def test_occupied_uniqueness_key_with_different_payload_conflicts(self) -> None:
        create_plan = self.plan()
        self._seed_exact_plan(create_plan)
        row = self.db.scalar(select(OfferCandidateRecord))
        assert row is not None
        row.price_eur = Decimal("9.99")
        self.db.commit()

        blocked = self.plan()
        self.assertEqual(blocked["result"], "BLOCKED_CONFLICT")
        self.assertEqual(blocked["offer_candidate_action"], "CONFLICT")
        self.assertIn("offer_uniqueness_key_payload_conflict", blocked["conflicts"])
        self.assertEqual(
            blocked["expected_deltas"]["first_apply"],
            {"source_snapshots": 0, "offer_candidates": 0},
        )

    def test_apply_requires_exact_authorization_and_replay_writes_zero(self) -> None:
        create_plan = self.plan()
        with self.assertRaisesRegex(
            LidlSemanticPersistenceError,
            "authorization",
        ):
            apply_lidl_v631_semantic_persistence_plan(
                db=self.db,
                reviewed_receipt_bytes=self.receipt,
                semantic_rows=[semantic_row()],
                row_binding_sha256=ROW_BINDING,
                source_binding=source_binding(),
                authorization={},
            )

        auth = _auth(create_plan)
        first = apply_lidl_v631_semantic_persistence_plan(
            db=self.db,
            reviewed_receipt_bytes=self.receipt,
            semantic_rows=[semantic_row()],
            row_binding_sha256=ROW_BINDING,
            source_binding=source_binding(),
            authorization=auth,
        )
        self.assertEqual(first["result"], "APPLY_PASS")
        self.assertEqual(first["source_snapshot_writes"], 1)
        self.assertEqual(first["offer_candidate_writes"], 1)
        self.assertEqual(first["post_apply_result"], "NO_OP_IDENTICAL")
        self.assertEqual(first["replay_writes"], 0)

        replay = apply_lidl_v631_semantic_persistence_plan(
            db=self.db,
            reviewed_receipt_bytes=self.receipt,
            semantic_rows=[semantic_row()],
            row_binding_sha256=ROW_BINDING,
            source_binding=source_binding(),
            authorization=auth,
        )
        self.assertEqual(replay["result"], "APPLY_NO_OP_IDENTICAL")
        self.assertEqual(replay["source_snapshot_writes"], 0)
        self.assertEqual(replay["offer_candidate_writes"], 0)
        self.assertEqual(replay["replay_writes"], 0)

    def test_apply_rejects_permission_widening(self) -> None:
        plan = self.plan()
        auth = _auth(plan)
        auth["permissions"] = dict(auth["permissions"])
        auth["permissions"]["production_publish"] = True
        with self.assertRaisesRegex(
            LidlSemanticPersistenceError,
            "permissions mismatch",
        ):
            apply_lidl_v631_semantic_persistence_plan(
                db=self.db,
                reviewed_receipt_bytes=self.receipt,
                semantic_rows=[semantic_row()],
                row_binding_sha256=ROW_BINDING,
                source_binding=source_binding(),
                authorization=auth,
            )


if __name__ == "__main__":
    unittest.main()
