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
