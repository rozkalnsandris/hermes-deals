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


class CatalogUiApiTest(unittest.TestCase):
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
    def _snapshot(chain: str, at: datetime) -> SourceSnapshot:
        return SourceSnapshot(id=uuid.uuid4(), source_chain=chain, source_url=f"https://example.invalid/{chain}", final_url=None, scope=None, collected_at=at, http_status=200, elapsed_ms=1, content_type="application/json", content_bytes=1, sha256=None, snapshot_path=None, keyword_hits={}, json_ld_blocks=0, strategy_hint="test", success=True, error=None)

    @staticmethod
    def _product(db: Session, *, display_name: str, normalized_name: str, brand: str) -> CanonicalProduct:
        product = CanonicalProduct(id=uuid.uuid4(), display_name=display_name, normalized_name=normalized_name, brand_display=brand.title(), brand_normalized=brand, item_quantity_value=Decimal("1000"), item_quantity_unit="ml", pack_count=1, gtin14=None, category_key=None)
        db.add(product); db.flush(); return product

    @staticmethod
    def _offer(*, snapshot: SourceSnapshot, chain: str, source_offer_id: str, store: str | None, price: str, at: datetime) -> OfferCandidateRecord:
        return OfferCandidateRecord(id=uuid.uuid4(), source_chain=chain, source_store_external_id=store, source_store_name=None, source_offer_id=source_offer_id, product_name_raw="Test Product", brand_raw="TEST", description_raw=None, package_text_raw="1 L", price_eur=Decimal(price), regular_price_eur=None, unit_price_eur=None, unit_label=None, discount_percent=None, app_price_eur=None, requires_app=False, coupon_required=False, valid_from=date(2026,7,25), valid_until=date(2026,7,31), source_url="https://example.invalid/offer", source_image_url=None, snapshot_id=snapshot.id, collected_at=at, parser_version="test-v1", raw_payload={})

    @staticmethod
    def _link(db: Session, product: CanonicalProduct, offer: OfferCandidateRecord) -> None:
        norm = OfferNormalization(id=uuid.uuid4(), offer_candidate_id=offer.id, normalizer_version="normalizer-v1.1", normalized_name=product.normalized_name, normalized_brand=product.brand_normalized, item_quantity_value=product.item_quantity_value, item_quantity_unit=product.item_quantity_unit, pack_count=product.pack_count, gtin14=None, category_key=None, evidence_json={})
        db.add(norm); db.flush()
        candidate = ProductMatchCandidate(id=uuid.uuid4(), offer_candidate_id=offer.id, offer_normalization_id=norm.id, canonical_product_id=product.id, matcher_version="matcher-v1.1", match_method="test", confidence=Decimal("0.99"), evidence_json={}, review_status="accepted", decision_reason="test", decided_at=datetime.now(timezone.utc))
        db.add(candidate); db.flush()
        db.add(OfferProductLink(id=uuid.uuid4(), offer_candidate_id=offer.id, canonical_product_id=product.id, source_match_candidate_id=candidate.id, link_method="test", confidence=Decimal("0.99")))

    def test_catalog_empty_is_stable(self) -> None:
        r=self.client.get("/api/v1/catalog?as_of=2026-07-25"); self.assertEqual(r.status_code,200); b=r.json(); self.assertEqual(b["count"],0); self.assertEqual(b["products"],[]); self.assertEqual(b["timezone"],"Europe/Berlin")

    def test_catalog_search_filters_name_or_brand(self) -> None:
        with self.Session.begin() as db:
            self._product(db,display_name="Oatly Haferdrink",normalized_name="haferdrink",brand="oatly")
            self._product(db,display_name="Almette Alpenfrischkäse",normalized_name="alpenfrischkäse",brand="almette")
        b=self.client.get("/api/v1/catalog?as_of=2026-07-25&q=oatly").json(); self.assertEqual(b["count"],1); self.assertEqual(b["products"][0]["display_name"],"Oatly Haferdrink")

    def test_catalog_single_offer_never_claims_comparison(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s=self._snapshot("edeka",at); db.add(s); o=self._offer(snapshot=s,chain="edeka",source_offer_id="edeka-1",store="071897",price="1.79",at=at); db.add(o); p=self._product(db,display_name="Oatly Haferdrink",normalized_name="haferdrink",brand="oatly"); self._link(db,p,o)
        p=self.client.get("/api/v1/catalog?as_of=2026-07-25").json()["products"][0]; self.assertEqual(p["comparison_status"],"single_current_offer"); self.assertFalse(p["comparison_available"]); self.assertEqual(p["retailer_count"],1); self.assertEqual(p["lowest_price_eur"],"1.79")

    def test_catalog_multi_store_exposes_safe_comparison(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s1=self._snapshot("edeka",at); s2=self._snapshot("aldi_nord",at); db.add_all([s1,s2])
            o1=self._offer(snapshot=s1,chain="edeka",source_offer_id="edeka-1",store="071897",price="1.99",at=at)
            o2=self._offer(snapshot=s2,chain="aldi_nord",source_offer_id="aldi-1",store=None,price="1.79",at=at)
            db.add_all([o1,o2]); p=self._product(db,display_name="Oatly Haferdrink",normalized_name="haferdrink",brand="oatly"); db.flush(); self._link(db,p,o1); self._link(db,p,o2)
        p=self.client.get("/api/v1/catalog?as_of=2026-07-25").json()["products"][0]; self.assertEqual(p["comparison_status"],"multi_store_comparison"); self.assertTrue(p["comparison_available"]); self.assertEqual(p["retailer_count"],2); self.assertEqual(p["lowest_price_eur"],"1.79"); self.assertEqual(len(p["current_offers"]),2)

    def test_ui_route_returns_family_interface(self) -> None:
        r=self.client.get("/ui"); self.assertEqual(r.status_code,200); self.assertIn("text/html",r.headers["content-type"]); self.assertIn("Ģimenes cenu skats",r.text); self.assertIn("/api/v1/catalog",r.text); self.assertIn("Cenu vēsture",r.text)

    def test_openapi_contains_catalog_but_ui_is_hidden(self) -> None:
        schema=self.client.get("/api/openapi.json").json(); self.assertIn("/api/v1/catalog",schema["paths"]); self.assertNotIn("/ui",schema["paths"])


if __name__ == "__main__":
    unittest.main()
