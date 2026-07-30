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


class UiBasketApiTest(unittest.TestCase):
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
    def product(db: Session, *, name: str, brand: str) -> CanonicalProduct:
        row = CanonicalProduct(id=uuid.uuid4(), display_name=name, normalized_name=name.casefold(), brand_display=brand, brand_normalized=brand.casefold(), item_quantity_value=Decimal("1000"), item_quantity_unit="ml", pack_count=1, gtin14=None, category_key=None)
        db.add(row); db.flush(); return row

    @staticmethod
    def offer(*, snapshot: SourceSnapshot, product_name: str, chain: str, offer_id: str, store: str | None, store_name: str | None, price: str, image: str | None, at: datetime) -> OfferCandidateRecord:
        return OfferCandidateRecord(id=uuid.uuid4(), source_chain=chain, source_store_external_id=store, source_store_name=store_name, source_offer_id=offer_id, product_name_raw=product_name, brand_raw=None, description_raw=None, package_text_raw="1 L", price_eur=Decimal(price), regular_price_eur=None, unit_price_eur=None, unit_label=None, discount_percent=None, app_price_eur=None, requires_app=False, coupon_required=False, valid_from=date(2026,7,25), valid_until=date(2026,7,31), source_url="https://example.invalid/offer", source_image_url=image, snapshot_id=snapshot.id, collected_at=at, parser_version="test-v1", raw_payload={})

    @staticmethod
    def link(db: Session, product: CanonicalProduct, offer: OfferCandidateRecord) -> None:
        norm = OfferNormalization(id=uuid.uuid4(), offer_candidate_id=offer.id, normalizer_version="normalizer-v1.1", normalized_name=product.normalized_name, normalized_brand=product.brand_normalized, item_quantity_value=product.item_quantity_value, item_quantity_unit=product.item_quantity_unit, pack_count=product.pack_count, gtin14=None, category_key=None, evidence_json={})
        db.add(norm); db.flush()
        candidate = ProductMatchCandidate(id=uuid.uuid4(), offer_candidate_id=offer.id, offer_normalization_id=norm.id, canonical_product_id=product.id, matcher_version="matcher-v1.1", match_method="test", confidence=Decimal("0.99"), evidence_json={}, review_status="accepted", decision_reason="test", decided_at=datetime.now(timezone.utc))
        db.add(candidate); db.flush()
        db.add(OfferProductLink(id=uuid.uuid4(), offer_candidate_id=offer.id, canonical_product_id=product.id, source_match_candidate_id=candidate.id, link_method="test", confidence=Decimal("0.99")))

    def seed(self, *, second_store_complete: bool = False):
        at = datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            edeka=self.snapshot("edeka",at); aldi=self.snapshot("aldi_nord",at); db.add_all([edeka,aldi])
            milk=self.product(db,name="Milk",brand="Brand A"); bread=self.product(db,name="Bread",brand="Brand B")
            e1=self.offer(snapshot=edeka,product_name="Milk",chain="edeka",offer_id="edeka-milk",store="071897",store_name="EDEKA Test",price="2.00",image="https://example.invalid/milk.jpg",at=at)
            e2=self.offer(snapshot=edeka,product_name="Bread",chain="edeka",offer_id="edeka-bread",store="071897",store_name="EDEKA Test",price="3.00",image=None,at=at)
            a1=self.offer(snapshot=aldi,product_name="Milk",chain="aldi_nord",offer_id="aldi-milk",store=None,store_name=None,price="1.50",image=None,at=at)
            db.add_all([e1,e2,a1]); db.flush(); self.link(db,milk,e1); self.link(db,bread,e2); self.link(db,milk,a1)
            if second_store_complete:
                a2=self.offer(snapshot=aldi,product_name="Bread",chain="aldi_nord",offer_id="aldi-bread",store=None,store_name=None,price="3.50",image=None,at=at)
                db.add(a2); db.flush(); self.link(db,bread,a2)
        return milk.id,bread.id

    def post_basket(self, items):
        return self.client.post("/api/v1/ui/basket/compare", json={"as_of":"2026-07-25","items":items})

    def test_empty_basket_is_422(self):
        self.assertEqual(self.post_basket([]).status_code,422)

    def test_missing_product_is_404(self):
        self.assertEqual(self.post_basket([{"canonical_product_id":str(uuid.uuid4()),"quantity":1}]).status_code,404)

    def test_duplicate_items_merge_quantity(self):
        milk,_=self.seed()
        body=self.post_basket([{"canonical_product_id":str(milk),"quantity":1},{"canonical_product_id":str(milk),"quantity":2}]).json()
        self.assertEqual(body["requested_product_count"],1); self.assertEqual(body["requested_unit_count"],3)
        edeka=next(s for s in body["retailer_scopes"] if s["source_chain"]=="edeka")
        self.assertEqual(edeka["lines"][0]["quantity"],3); self.assertEqual(edeka["lines"][0]["line_total_eur"],"6.00")

    def test_one_complete_store_is_not_called_comparison(self):
        milk,bread=self.seed()
        body=self.post_basket([{"canonical_product_id":str(milk),"quantity":2},{"canonical_product_id":str(bread),"quantity":1}]).json()
        self.assertEqual(body["complete_retailer_scope_count"],1); self.assertFalse(body["comparison_available"]); self.assertIsNone(body["best_complete_total_eur"]); self.assertEqual(body["best_complete_scopes"],[])

    def test_partial_store_exposes_missing_product(self):
        milk,bread=self.seed()
        body=self.post_basket([{"canonical_product_id":str(milk),"quantity":1},{"canonical_product_id":str(bread),"quantity":1}]).json()
        aldi=next(s for s in body["retailer_scopes"] if s["source_chain"]=="aldi_nord")
        self.assertFalse(aldi["complete_basket"]); self.assertEqual(aldi["covered_product_count"],1); self.assertEqual(aldi["missing_product_ids"],[str(bread)])

    def test_two_complete_stores_enable_safe_comparison(self):
        milk,bread=self.seed(second_store_complete=True)
        body=self.post_basket([{"canonical_product_id":str(milk),"quantity":2},{"canonical_product_id":str(bread),"quantity":1}]).json()
        self.assertEqual(body["complete_retailer_scope_count"],2); self.assertTrue(body["comparison_available"]); self.assertEqual(body["best_complete_total_eur"],"6.50")
        self.assertEqual([s["source_chain"] for s in body["best_complete_scopes"]],["aldi_nord"])

    def test_catalog_exposes_current_product_image(self):
        milk,_=self.seed()
        body=self.client.get("/api/v1/catalog?as_of=2026-07-25&q=milk").json()
        self.assertEqual(body["count"],1); self.assertEqual(body["products"][0]["primary_image_url"],"https://example.invalid/milk.jpg"); self.assertEqual(body["products"][0]["id"],str(milk))

    def test_ui_contains_shopping_list_detail_and_basket_features(self):
        response=self.client.get("/ui"); self.assertEqual(response.status_code,200)
        for marker in ("hermesDeals.shoppingList.v1","/api/v1/ui/basket/compare","Produkta detaļas","Pievienot sarakstam","best_complete_total_eur","Cenu vēstures grafiks"):
            self.assertIn(marker,response.text)


if __name__ == "__main__":
    unittest.main()
