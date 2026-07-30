from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import (
    Base,
    OfferCandidateRecord,
    OfferReviewItem,
    OfferReviewRevision,
    SourceSnapshot,
)
from app.review_queue import seed_review_item
from app.lidl_weekly_review_bridge import (
    apply_weekly_review_bridge,
    create_review_from_page_alert_hint,
    plan_weekly_review_bridge,
    resolve_original_lidl_snapshot,
)


class ReviewQueueApiTest(unittest.TestCase):
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

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.snapshot_id = uuid.uuid4()

        with self.Session.begin() as db:
            db.add(
                SourceSnapshot(
                    id=self.snapshot_id,
                    source_chain="lidl",
                    source_url="https://www.lidl.de/c/online-prospekte/s10005610/",
                    final_url="https://example.invalid/flyer.pdf",
                    scope="public_default_flyer",
                    collected_at=datetime(
                        2026,
                        7,
                        28,
                        20,
                        0,
                        tzinfo=timezone.utc,
                    ),
                    http_status=200,
                    elapsed_ms=10,
                    content_type="application/pdf",
                    content_bytes=123,
                    sha256="a" * 64,
                    snapshot_path="/immutable/lidl/kw32/source.pdf",
                    keyword_hits={},
                    json_ld_blocks=0,
                    strategy_hint="test_lidl_flyer",
                    success=True,
                    error=None,
                )
            )

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def seed(
        self,
        suffix: str = "1",
        *,
        scope: str = "review",
    ) -> str:
        with self.Session() as db:
            row = seed_review_item(
                db,
                source_chain="lidl",
                source_snapshot_id=self.snapshot_id,
                source_flyer_key=(
                    "20260803-20260808-r21-c20598d30ff5"
                ),
                source_row_key=f"page14-magifix-{suffix}",
                page_number=14,
                parser_version=(
                    "lidl-pdf-v08c-r61-shadow-v631"
                ),
                reason_codes=["scope_requires_review"],
                original_payload={
                    "product_name": "MAGGI Fix",
                    "package_text": (
                        "36/26/30/33/39/41/40/47 g"
                    ),
                    "price_eur": "0.39",
                    "valid_from": "2026-08-03",
                    "valid_until": "2026-08-08",
                    "scope": scope,
                    "channel": "physical_store",
                },
                provenance_json={
                    "source_url": (
                        "https://example.invalid/flyer.pdf"
                    ),
                    "pdf_sha256": "a" * 64,
                    "raw_sha256": "b" * 64,
                    "crop_url": (
                        "/future-crops/"
                        "kw32-p14-magifix.webp"
                    ),
                },
            )
            return str(row.id)

    def weekly_candidate(self) -> dict:
        return {
            "candidate_key": "weekly-maxi-king",
            "flyer_key": "20260803-20260808-r21-c20598d30ff5",
            "page": 16,
            "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
            "source_raw_sha256": "a" * 64,
            "source_pdf_sha256": "c" * 64,
            "workflow_version": "lidl-weekly-completeness-review-alerts-v1",
            "evidence_kind": "native_unowned_display_price",
            "product_name": "KINDER Maxi King",
            "price_eur": "1.59",
            "title_bbox": [1.0, 2.0, 3.0, 4.0],
        }

    def weekly_alert(self) -> dict:
        return {
            "alert_key": "weekly-page-one",
            "flyer_key": "20260803-20260808-r21-c20598d30ff5",
            "page": 1,
            "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
            "source_raw_sha256": "a" * 64,
            "source_pdf_sha256": "c" * 64,
            "workflow_version": "lidl-weekly-completeness-review-alerts-v1",
            "page_gate": "review_profile_weekly_physical_deals",
            "page_gate_source": "review_profile",
            "hint_count": 2,
            "hints": [
                {
                    "product_name_hint": "Buttercroissant",
                    "native_title": "Buttercroissant",
                    "scope": "review",
                    "title_bbox": [1.0, 2.0, 3.0, 4.0],
                    "evidence_kind": "native_unrepresented_strict_title",
                },
                {
                    "product_name_hint": "LANGNESE Magnum",
                    "native_title": "LANGNESE Magnum",
                    "scope": "review",
                    "title_bbox": [5.0, 6.0, 7.0, 8.0],
                    "evidence_kind": "native_unrepresented_strict_title",
                },
            ],
        }

    def test_weekly_bridge_resolves_original_snapshot(self) -> None:
        with self.Session() as db:
            resolved = resolve_original_lidl_snapshot(
                db,
                source_raw_sha256="a" * 64,
            )
            self.assertEqual(resolved.id, self.snapshot_id)

    def test_weekly_bridge_seeds_native_candidate_and_page_alert(self) -> None:
        with self.Session() as db:
            result = apply_weekly_review_bridge(
                db,
                candidates=[self.weekly_candidate()],
                page_alerts=[self.weekly_alert()],
            )
        self.assertEqual(result["candidate_seed_count"], 1)
        self.assertEqual(result["page_alert_seed_count"], 1)
        self.assertEqual(len(result["seeded_candidate_ids"]), 1)
        self.assertEqual(len(result["seeded_page_alert_ids"]), 1)

    def test_weekly_bridge_suppresses_existing_review_product(self) -> None:
        with self.Session() as db:
            seed_review_item(
                db,
                source_chain="lidl",
                source_snapshot_id=self.snapshot_id,
                source_flyer_key="20260803-20260808-r21-c20598d30ff5",
                source_row_key="already-reviewed-maxi",
                page_number=16,
                parser_version="old",
                reason_codes=["scope_requires_review"],
                original_payload={
                    "product_name": "KINDER Maxi King",
                    "price_eur": "1.59",
                    "valid_from": "2026-08-03",
                    "valid_until": "2026-08-08",
                    "scope": "review",
                    "channel": "physical_store",
                },
                provenance_json={},
            )
            plan = plan_weekly_review_bridge(
                db,
                candidates=[self.weekly_candidate()],
                page_alerts=[self.weekly_alert()],
            )
        self.assertEqual(plan["candidate_seed_count"], 0)
        self.assertEqual(plan["candidate_suppressed_count"], 1)

    def test_weekly_bridge_removes_resolved_page_alert_hints(self) -> None:
        with self.Session() as db:
            seed_review_item(
                db,
                source_chain="lidl",
                source_snapshot_id=self.snapshot_id,
                source_flyer_key="20260803-20260808-r21-c20598d30ff5",
                source_row_key="already-reviewed-butter",
                page_number=1,
                parser_version="old",
                reason_codes=["scope_requires_review"],
                original_payload={
                    "product_name": "Buttercroissant",
                    "price_eur": "0.24",
                    "valid_from": "2026-08-03",
                    "valid_until": "2026-08-08",
                    "scope": "review",
                    "channel": "physical_store",
                },
                provenance_json={},
            )
            plan = plan_weekly_review_bridge(
                db,
                candidates=[self.weekly_candidate()],
                page_alerts=[self.weekly_alert()],
            )
        self.assertEqual(plan["page_alert_seed_count"], 1)
        alert = plan["planned_page_alerts"][0]
        self.assertEqual(alert["hint_count"], 1)
        self.assertEqual(alert["hints"][0]["product_name_hint"], "LANGNESE Magnum")

    def test_page_alert_hint_creates_idempotent_editable_product_review(self) -> None:
        with self.Session() as db:
            result = apply_weekly_review_bridge(
                db,
                candidates=[self.weekly_candidate()],
                page_alerts=[self.weekly_alert()],
            )
            alert_id = uuid.UUID(result["seeded_page_alert_ids"][0])
            first = create_review_from_page_alert_hint(
                db,
                alert_item_id=alert_id,
                hint_index=1,
            )
            second = create_review_from_page_alert_hint(
                db,
                alert_item_id=alert_id,
                hint_index=1,
            )
            self.assertEqual(first.id, second.id)
            self.assertEqual(first.original_payload["product_name"], "LANGNESE Magnum")
            self.assertEqual(first.original_payload["valid_from"], "2026-08-03")
            self.assertEqual(first.original_payload["valid_until"], "2026-08-08")
            self.assertIsNone(first.original_payload["price_eur"])

    def test_page_alert_api_cannot_publish_and_can_create_hint_review(self) -> None:
        with self.Session() as db:
            result = apply_weekly_review_bridge(
                db,
                candidates=[self.weekly_candidate()],
                page_alerts=[self.weekly_alert()],
            )
            alert_id = result["seeded_page_alert_ids"][0]

        detail = self.client.get(f"/api/v1/review-items/{alert_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["review_kind"], "page_alert")

        blocked = self.client.post(
            f"/api/v1/review-items/{alert_id}/approve",
            json={"note": "must not publish"},
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)

        created = self.client.post(
            f"/api/v1/review-items/{alert_id}/page-alert/hints/0/create"
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["review_kind"], "product")
        self.assertEqual(
            created.json()["effective_payload"]["product_name"],
            "Buttercroissant",
        )

    def test_seed_is_idempotent_and_original_is_immutable(
        self,
    ) -> None:
        item_id = self.seed()
        self.assertEqual(item_id, self.seed())

        body = self.client.get(
            f"/api/v1/review-items/{item_id}"
        ).json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(
            body["original_payload"]["scope"],
            "review",
        )
        self.assertEqual(
            body["revisions"][0]["action"],
            "seed",
        )

        saved = self.client.patch(
            f"/api/v1/review-items/{item_id}",
            json={
                "corrections": {
                    "scope": "in_scope",
                    "product_name": "MAGGI Fix",
                },
                "note": "food product",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["status"], "draft")
        self.assertEqual(
            body["effective_payload"]["scope"],
            "in_scope",
        )
        self.assertEqual(
            body["original_payload"]["scope"],
            "review",
        )

    def test_approve_and_publish_uses_derived_snapshot(
        self,
    ) -> None:
        item_id = self.seed()
        saved = self.client.patch(
            f"/api/v1/review-items/{item_id}",
            json={
                "corrections": {"scope": "in_scope"},
                "note": "manual scope confirmation",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        approved = self.client.post(
            f"/api/v1/review-items/{item_id}/approve",
            json={"note": "publish"},
        )
        self.assertEqual(
            approved.status_code,
            200,
            approved.text,
        )
        body = approved.json()
        self.assertEqual(body["status"], "approved")
        self.assertIsNotNone(
            body["published_offer_candidate_id"]
        )
        self.assertEqual(
            body["original_payload"]["scope"],
            "review",
        )
        self.assertEqual(
            body["corrected_payload"]["scope"],
            "in_scope",
        )

        again = self.client.post(
            f"/api/v1/review-items/{item_id}/approve",
            json={"note": "retry"},
        )
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(
            again.json()["published_offer_candidate_id"],
            body["published_offer_candidate_id"],
        )

        with self.Session() as db:
            item = db.get(
                OfferReviewItem,
                uuid.UUID(item_id),
            )
            offer = db.get(
                OfferCandidateRecord,
                item.published_offer_candidate_id,
            )
            self.assertIsNotNone(offer)
            self.assertEqual(
                offer.product_name_raw,
                "MAGGI Fix",
            )
            self.assertEqual(
                offer.price_eur,
                Decimal("0.39"),
            )
            self.assertEqual(
                offer.raw_payload[
                    "review_original_source_snapshot_id"
                ],
                str(self.snapshot_id),
            )
            self.assertEqual(
                offer.raw_payload["review_source"],
                "manual",
            )
            self.assertNotEqual(
                offer.snapshot_id,
                self.snapshot_id,
            )
            derived = db.get(
                SourceSnapshot,
                offer.snapshot_id,
            )
            self.assertEqual(
                derived.strategy_hint,
                "manual_review_v1",
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        OfferCandidateRecord
                    )
                ),
                1,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        SourceSnapshot
                    )
                ),
                2,
            )
            revisions = list(
                db.scalars(
                    select(OfferReviewRevision)
                    .where(
                        OfferReviewRevision.review_item_id
                        == item.id
                    )
                    .order_by(
                        OfferReviewRevision.revision_no
                    )
                )
            )
            self.assertEqual(
                [row.action for row in revisions],
                ["seed", "draft", "approve"],
            )

    def test_approval_fails_closed_until_scope_confirmed(
        self,
    ) -> None:
        item_id = self.seed()
        response = self.client.post(
            f"/api/v1/review-items/{item_id}/approve",
            json={"note": "too early"},
        )
        self.assertEqual(response.status_code, 409)

        with self.Session() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        OfferCandidateRecord
                    )
                ),
                0,
            )

    def test_reject_and_reopen_preserve_audit_trail(
        self,
    ) -> None:
        item_id = self.seed("2")
        rejected = self.client.post(
            f"/api/v1/review-items/{item_id}/reject",
            json={"note": "not relevant"},
        )
        self.assertEqual(
            rejected.status_code,
            200,
            rejected.text,
        )
        self.assertEqual(
            rejected.json()["status"],
            "rejected",
        )

        reopened = self.client.post(
            f"/api/v1/review-items/{item_id}/reopen",
            json={"note": "check again"},
        )
        self.assertEqual(
            reopened.status_code,
            200,
            reopened.text,
        )
        self.assertEqual(
            reopened.json()["status"],
            "pending",
        )
        self.assertEqual(
            [
                row["action"]
                for row in reopened.json()["revisions"]
            ],
            ["seed", "reject", "reopen"],
        )

    def test_summary_list_and_ui(self) -> None:
        self.seed("3")

        listing = self.client.get(
            "/api/v1/review-items"
            "?source_chain=lidl&status=pending"
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            listing.json()["count"],
            1,
        )

        summary = self.client.get(
            "/api/v1/review-items/summary"
            "?source_chain=lidl"
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(
            summary.json()["open_count"],
            1,
        )

        ui = self.client.get("/ui/review")
        self.assertEqual(ui.status_code, 200)
        self.assertIn(
            "Apstiprināt un publicēt",
            ui.text,
        )
        self.assertIn(
            "/api/v1/review-items",
            ui.text,
        )
        self.assertIn(
            "Oriģinālais parsera ieraksts",
            ui.text,
        )


if __name__ == "__main__":
    unittest.main()
