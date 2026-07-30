from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import (
    Base,
    CanonicalProduct,
    OfferCandidateRecord,
    OfferNormalization,
    OfferProductLink,
    ProductMatchCandidate,
    SourceSnapshot,
)


class CanonicalPriceHistoryApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    @staticmethod
    def _snapshot(chain: str, collected_at: datetime) -> SourceSnapshot:
        return SourceSnapshot(
            id=uuid.uuid4(),
            source_chain=chain,
            source_url=f"https://example.invalid/{chain}",
            final_url=None,
            scope=None,
            collected_at=collected_at,
            http_status=200,
            elapsed_ms=1,
            content_type="application/json",
            content_bytes=1,
            sha256=None,
            snapshot_path=None,
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint="test",
            success=True,
            error=None,
        )

    @staticmethod
    def _offer(*, snapshot, chain, source_offer_id, store, price, collected_at, name):
        return OfferCandidateRecord(
            id=uuid.uuid4(),
            source_chain=chain,
            source_store_external_id=store,
            source_store_name=None,
            source_offer_id=source_offer_id,
            product_name_raw=name,
            brand_raw=None,
            description_raw=None,
            package_text_raw=None,
            price_eur=Decimal(price),
            regular_price_eur=None,
            unit_price_eur=None,
            unit_label=None,
            discount_percent=None,
            app_price_eur=None,
            requires_app=False,
            coupon_required=False,
            valid_from=None,
            valid_until=None,
            source_url="https://example.invalid/offer",
            source_image_url=None,
            snapshot_id=snapshot.id,
            collected_at=collected_at,
            parser_version="test-v1",
            raw_payload={},
        )

    def _link_seed(self, db, product, offer):
        normalization = OfferNormalization(
            id=uuid.uuid4(),
            offer_candidate_id=offer.id,
            normalizer_version="normalizer-v1.1",
            normalized_name=product.normalized_name,
            normalized_brand=product.brand_normalized,
            item_quantity_value=product.item_quantity_value,
            item_quantity_unit=product.item_quantity_unit,
            pack_count=product.pack_count,
            gtin14=None,
            category_key=None,
            evidence_json={},
        )
        db.add(normalization)
        db.flush()

        candidate = ProductMatchCandidate(
            id=uuid.uuid4(),
            offer_candidate_id=offer.id,
            offer_normalization_id=normalization.id,
            canonical_product_id=product.id,
            matcher_version="matcher-v1.1",
            match_method="test",
            confidence=Decimal("0.99"),
            evidence_json={},
            review_status="accepted",
            decision_reason="test",
            decided_at=datetime.now(timezone.utc),
        )
        db.add(candidate)
        db.flush()

        db.add(
            OfferProductLink(
                id=uuid.uuid4(),
                offer_candidate_id=offer.id,
                canonical_product_id=product.id,
                source_match_candidate_id=candidate.id,
                link_method="test",
                confidence=Decimal("0.99"),
            )
        )

    def test_history_follows_stable_source_offer_id_across_snapshots(self):
        t1 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

        with self.Session.begin() as db:
            s1 = self._snapshot("aldi_nord", t1)
            s2 = self._snapshot("aldi_nord", t2)
            db.add_all([s1, s2])

            old = self._offer(
                snapshot=s1, chain="aldi_nord", source_offer_id="stable-1",
                store=None, price="1.11", collected_at=t1, name="Alpenfrischkäse",
            )
            newest = self._offer(
                snapshot=s2, chain="aldi_nord", source_offer_id="stable-1",
                store=None, price="1.09", collected_at=t2, name="Alpenfrischkäse",
            )
            unrelated = self._offer(
                snapshot=s2, chain="aldi_nord", source_offer_id="other",
                store=None, price="9.99", collected_at=t2, name="Other",
            )
            db.add_all([old, newest, unrelated])

            product = CanonicalProduct(
                id=uuid.uuid4(),
                display_name="Almette Alpenfrischkäse",
                normalized_name="alpenfrischkäse",
                brand_display="Almette",
                brand_normalized="almette",
                item_quantity_value=Decimal("150"),
                item_quantity_unit="g",
                pack_count=1,
                gtin14=None,
                category_key=None,
            )
            db.add(product)
            db.flush()
            self._link_seed(db, product, newest)
            product_id = product.id

        response = self.client.get(
            f"/api/v1/canonical-products/{product_id}/price-history"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [row["price_eur"] for row in body["observations"]],
            ["1.09", "1.11"],
        )
        self.assertTrue(all(
            row["source_offer_id"] == "stable-1"
            for row in body["observations"]
        ))

    def test_history_preserves_store_scope_for_same_source_offer_id(self):
        t = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

        with self.Session.begin() as db:
            chosen_snapshot = self._snapshot("edeka", t)
            other_snapshot = self._snapshot("edeka", t)
            db.add_all([chosen_snapshot, other_snapshot])

            chosen = self._offer(
                snapshot=chosen_snapshot, chain="edeka", source_offer_id="same-id",
                store="071897", price="1.79", collected_at=t, name="Oatly Haferdrink",
            )
            other = self._offer(
                snapshot=other_snapshot, chain="edeka", source_offer_id="same-id",
                store="OTHER", price="0.01", collected_at=t, name="Oatly Haferdrink",
            )
            db.add_all([chosen, other])

            product = CanonicalProduct(
                id=uuid.uuid4(),
                display_name="Oatly Haferdrink",
                normalized_name="haferdrink",
                brand_display="Oatly",
                brand_normalized="oatly",
                item_quantity_value=Decimal("1000"),
                item_quantity_unit="ml",
                pack_count=1,
                gtin14=None,
                category_key=None,
            )
            db.add(product)
            db.flush()
            self._link_seed(db, product, chosen)
            product_id = product.id

        response = self.client.get(
            f"/api/v1/canonical-products/{product_id}/price-history"
        )
        self.assertEqual(response.status_code, 200)
        observations = response.json()["observations"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["source_store_external_id"], "071897")
        self.assertEqual(observations[0]["price_eur"], "1.79")

    def test_missing_canonical_product_returns_404(self):
        response = self.client.get(
            f"/api/v1/canonical-products/{uuid.uuid4()}/price-history"
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
