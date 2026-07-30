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
from app.models import Base, CanonicalProduct, OfferCandidateRecord, OfferNormalization, OfferProductLink, ProductMatchCandidate, SourceSnapshot


class UiOverviewFiltersApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, class_=Session, expire_on_commit=False)

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
    def snapshot(chain: str, at: datetime) -> SourceSnapshot:
        return SourceSnapshot(id=uuid.uuid4(), source_chain=chain, source_url=f"https://example.invalid/{chain}", final_url=None, scope=None, collected_at=at, http_status=200, elapsed_ms=1, content_type="application/json", content_bytes=1, sha256=None, snapshot_path=None, keyword_hits={}, json_ld_blocks=0, strategy_hint="test", success=True, error=None)

    @staticmethod
    def product(db: Session, *, name: str, normalized: str, brand: str) -> CanonicalProduct:
        row = CanonicalProduct(id=uuid.uuid4(), display_name=name, normalized_name=normalized, brand_display=brand.title(), brand_normalized=brand, item_quantity_value=Decimal("1000"), item_quantity_unit="ml", pack_count=1, gtin14=None, category_key=None)
        db.add(row); db.flush(); return row

    @staticmethod
    def offer(*, snapshot: SourceSnapshot, chain: str, source_offer_id: str, store: str | None, price: str, valid_from: date, valid_until: date, at: datetime) -> OfferCandidateRecord:
        return OfferCandidateRecord(id=uuid.uuid4(), source_chain=chain, source_store_external_id=store, source_store_name=None, source_offer_id=source_offer_id, product_name_raw="Test Product", brand_raw="TEST", description_raw=None, package_text_raw="1 L", price_eur=Decimal(price), regular_price_eur=None, unit_price_eur=None, unit_label=None, discount_percent=None, app_price_eur=None, requires_app=False, coupon_required=False, valid_from=valid_from, valid_until=valid_until, source_url="https://example.invalid/offer", source_image_url=None, snapshot_id=snapshot.id, collected_at=at, parser_version="test-v1", raw_payload={})

    @staticmethod
    def link(db: Session, product: CanonicalProduct, offer: OfferCandidateRecord) -> None:
        norm = OfferNormalization(id=uuid.uuid4(), offer_candidate_id=offer.id, normalizer_version="normalizer-v1.1", normalized_name=product.normalized_name, normalized_brand=product.brand_normalized, item_quantity_value=product.item_quantity_value, item_quantity_unit=product.item_quantity_unit, pack_count=product.pack_count, gtin14=None, category_key=None, evidence_json={})
        db.add(norm); db.flush()
        candidate = ProductMatchCandidate(id=uuid.uuid4(), offer_candidate_id=offer.id, offer_normalization_id=norm.id, canonical_product_id=product.id, matcher_version="matcher-v1.1", match_method="test", confidence=Decimal("0.99"), evidence_json={}, review_status="accepted", decision_reason="test", decided_at=datetime.now(timezone.utc))
        db.add(candidate); db.flush()
        db.add(OfferProductLink(id=uuid.uuid4(), offer_candidate_id=offer.id, canonical_product_id=product.id, source_match_candidate_id=candidate.id, link_method="test", confidence=Decimal("0.99")))

    def seed_two_products(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            edeka = self.snapshot("edeka", at); aldi = self.snapshot("aldi_nord", at); db.add_all([edeka, aldi])
            p1 = self.product(db, name="Oatly Haferdrink", normalized="haferdrink", brand="oatly")
            p2 = self.product(db, name="Almette Alpenfrischkäse", normalized="alpenfrischkäse", brand="almette")
            o1 = self.offer(snapshot=edeka, chain="edeka", source_offer_id="edeka-oatly", store="071897", price="1.99", valid_from=date(2026,7,25), valid_until=date(2026,7,31), at=at)
            o2 = self.offer(snapshot=aldi, chain="aldi_nord", source_offer_id="aldi-oatly", store=None, price="1.79", valid_from=date(2026,7,25), valid_until=date(2026,7,31), at=at)
            expired = self.offer(snapshot=edeka, chain="edeka", source_offer_id="edeka-almette", store="071897", price="1.11", valid_from=date(2026,7,1), valid_until=date(2026,7,10), at=at)
            db.add_all([o1, o2, expired]); db.flush()
            self.link(db, p1, o1); self.link(db, p1, o2); self.link(db, p2, expired)

    def test_overview_empty_is_stable(self) -> None:
        body = self.client.get("/api/v1/ui/overview?as_of=2026-07-25").json()
        self.assertEqual(body["total_products"], 0); self.assertEqual(body["current_offer_count"], 0); self.assertEqual(body["retailers"], [])

    def test_overview_aggregates_current_scope(self) -> None:
        self.seed_two_products()
        body = self.client.get("/api/v1/ui/overview?as_of=2026-07-25").json()
        self.assertEqual(body["total_products"], 2); self.assertEqual(body["products_with_current_offers"], 1); self.assertEqual(body["products_without_current_offers"], 1)
        self.assertEqual(body["comparison_ready_products"], 1); self.assertEqual(body["current_offer_count"], 2); self.assertEqual(body["retailer_count"], 2)
        self.assertEqual({r["source_chain"] for r in body["retailers"]}, {"aldi_nord", "edeka"})

    def test_catalog_retailer_filter(self) -> None:
        self.seed_two_products()
        body = self.client.get("/api/v1/catalog?as_of=2026-07-25&retailer=aldi_nord").json()
        self.assertEqual(body["count"], 1); self.assertEqual(body["products"][0]["display_name"], "Oatly Haferdrink")

    def test_catalog_current_only(self) -> None:
        self.seed_two_products()
        body = self.client.get("/api/v1/catalog?as_of=2026-07-25&current_only=true").json()
        self.assertEqual(body["count"], 1); self.assertEqual(body["products"][0]["comparison_status"], "multi_store_comparison")

    def test_catalog_comparison_only(self) -> None:
        self.seed_two_products()
        body = self.client.get("/api/v1/catalog?as_of=2026-07-25&comparison_only=true").json()
        self.assertEqual(body["count"], 1); self.assertTrue(body["products"][0]["comparison_available"])

    def test_catalog_price_sort(self) -> None:
        self.seed_two_products()
        body = self.client.get("/api/v1/catalog?as_of=2026-07-25&sort=price_asc").json()
        self.assertEqual(body["products"][0]["display_name"], "Oatly Haferdrink")
        self.assertEqual(body["products"][-1]["display_name"], "Almette Alpenfrischkäse")

    def test_ui_contains_phase5b_family_features(self) -> None:
        response = self.client.get("/ui")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Cenas bez minējumiem.", response.text)
        self.assertIn("/api/v1/ui/overview", response.text)
        self.assertIn("comparison_only", response.text)
        self.assertIn("Cenu vēstures grafiks", response.text)
        self.assertIn("bottom-nav", response.text)


if __name__ == "__main__":
    unittest.main()
