from __future__ import annotations

from datetime import date, datetime, timezone
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


class CanonicalCurrentOffersApiTest(unittest.TestCase):
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
    def _offer(
        *,
        snapshot: SourceSnapshot,
        chain: str,
        source_offer_id: str,
        store: str | None,
        price: str,
        collected_at: datetime,
        valid_from: date | None,
        valid_until: date | None,
    ) -> OfferCandidateRecord:
        return OfferCandidateRecord(
            id=uuid.uuid4(),
            source_chain=chain,
            source_store_external_id=store,
            source_store_name=None,
            source_offer_id=source_offer_id,
            product_name_raw="Test Product",
            brand_raw="TEST",
            description_raw=None,
            package_text_raw="1 kg",
            price_eur=Decimal(price),
            regular_price_eur=None,
            unit_price_eur=None,
            unit_label=None,
            discount_percent=None,
            app_price_eur=None,
            requires_app=False,
            coupon_required=False,
            valid_from=valid_from,
            valid_until=valid_until,
            source_url="https://example.invalid/offer",
            source_image_url=None,
            snapshot_id=snapshot.id,
            collected_at=collected_at,
            parser_version="test-v1",
            raw_payload={},
        )

    def _product(self, db: Session) -> CanonicalProduct:
        product = CanonicalProduct(
            id=uuid.uuid4(),
            display_name="Test Product",
            normalized_name="test product",
            brand_display="Test",
            brand_normalized="test",
            item_quantity_value=Decimal("1000"),
            item_quantity_unit="g",
            pack_count=1,
            gtin14=None,
            category_key=None,
        )
        db.add(product)
        db.flush()
        return product

    def _link_seed(
        self,
        db: Session,
        product: CanonicalProduct,
        offer: OfferCandidateRecord,
    ) -> None:
        norm = OfferNormalization(
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
        db.add(norm)
        db.flush()

        candidate = ProductMatchCandidate(
            id=uuid.uuid4(),
            offer_candidate_id=offer.id,
            offer_normalization_id=norm.id,
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

    def test_inclusive_validity_boundaries_are_current(self) -> None:
        collected = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)

        with self.Session.begin() as db:
            snapshot = self._snapshot("edeka", collected)
            db.add(snapshot)
            offer = self._offer(
                snapshot=snapshot,
                chain="edeka",
                source_offer_id="offer-1",
                store="071897",
                price="1.11",
                collected_at=collected,
                valid_from=date(2026, 7, 20),
                valid_until=date(2026, 7, 25),
            )
            db.add(offer)
            product = self._product(db)
            self._link_seed(db, product, offer)
            product_id = product.id

        response = self.client.get(
            f"/api/v1/canonical-products/{product_id}/current-offers?as_of=2026-07-25"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["as_of"], "2026-07-25")
        self.assertEqual(body["timezone"], "Europe/Berlin")
        self.assertEqual(len(body["offers"]), 1)

    def test_future_and_expired_offers_are_excluded(self) -> None:
        collected = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)

        with self.Session.begin() as db:
            snap1 = self._snapshot("edeka", collected)
            snap2 = self._snapshot("aldi_nord", collected)
            db.add_all([snap1, snap2])

            expired = self._offer(
                snapshot=snap1,
                chain="edeka",
                source_offer_id="expired",
                store="071897",
                price="1.11",
                collected_at=collected,
                valid_from=date(2026, 7, 20),
                valid_until=date(2026, 7, 24),
            )
            future = self._offer(
                snapshot=snap2,
                chain="aldi_nord",
                source_offer_id="future",
                store=None,
                price="0.99",
                collected_at=collected,
                valid_from=date(2026, 7, 27),
                valid_until=date(2026, 8, 1),
            )
            db.add_all([expired, future])
            product = self._product(db)
            db.flush()
            self._link_seed(db, product, expired)
            self._link_seed(db, product, future)
            product_id = product.id

        response = self.client.get(
            f"/api/v1/canonical-products/{product_id}/current-offers?as_of=2026-07-25"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["offers"], [])

    def test_unknown_validity_is_not_current(self) -> None:
        collected = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)

        with self.Session.begin() as db:
            snapshot = self._snapshot("edeka", collected)
            db.add(snapshot)
            offer = self._offer(
                snapshot=snapshot,
                chain="edeka",
                source_offer_id="unknown-validity",
                store="071897",
                price="1.11",
                collected_at=collected,
                valid_from=None,
                valid_until=None,
            )
            db.add(offer)
            product = self._product(db)
            self._link_seed(db, product, offer)
            product_id = product.id

        response = self.client.get(
            f"/api/v1/canonical-products/{product_id}/current-offers?as_of=2026-07-25"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["offers"], [])

    def test_duplicate_snapshots_collapse_to_newest_observation(self) -> None:
        t1 = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)

        with self.Session.begin() as db:
            s1 = self._snapshot("edeka", t1)
            s2 = self._snapshot("edeka", t2)
            db.add_all([s1, s2])

            old = self._offer(
                snapshot=s1,
                chain="edeka",
                source_offer_id="stable-id",
                store="071897",
                price="1.29",
                collected_at=t1,
                valid_from=date(2026, 7, 20),
                valid_until=date(2026, 7, 25),
            )
            new = self._offer(
                snapshot=s2,
                chain="edeka",
                source_offer_id="stable-id",
                store="071897",
                price="1.11",
                collected_at=t2,
                valid_from=date(2026, 7, 20),
                valid_until=date(2026, 7, 25),
            )
            db.add_all([old, new])
            product = self._product(db)
            self._link_seed(db, product, new)
            product_id = product.id

        response = self.client.get(
            f"/api/v1/canonical-products/{product_id}/current-offers?as_of=2026-07-25"
        )
        self.assertEqual(response.status_code, 200)
        offers = response.json()["offers"]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price_eur"], "1.11")

    def test_missing_canonical_product_returns_404(self) -> None:
        response = self.client.get(
            f"/api/v1/canonical-products/{uuid.uuid4()}/current-offers?as_of=2026-07-25"
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
