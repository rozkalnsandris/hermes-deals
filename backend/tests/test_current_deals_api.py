from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import patch
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


class CurrentDealsApiTest(unittest.TestCase):
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
    def snapshot(chain: str, at: datetime) -> SourceSnapshot:
        return SourceSnapshot(
            id=uuid.uuid4(),
            source_chain=chain,
            source_url=f"https://example.invalid/{chain}",
            final_url=None,
            scope=None,
            collected_at=at,
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
    def offer(
        *,
        snapshot: SourceSnapshot,
        chain: str,
        source_offer_id: str | None,
        store: str | None,
        name: str,
        brand: str | None,
        price: str,
        valid_from: date | None,
        valid_until: date | None,
        collected_at: datetime,
    ) -> OfferCandidateRecord:
        return OfferCandidateRecord(
            id=uuid.uuid4(),
            source_chain=chain,
            source_store_external_id=store,
            source_store_name=None,
            source_offer_id=source_offer_id,
            product_name_raw=name,
            brand_raw=brand,
            description_raw=None,
            package_text_raw="500 g",
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
            source_image_url="https://example.invalid/image.jpg",
            snapshot_id=snapshot.id,
            collected_at=collected_at,
            parser_version="test-v1",
            raw_payload={},
        )

    @staticmethod
    def link(db: Session, offer: OfferCandidateRecord) -> CanonicalProduct:
        product = CanonicalProduct(
            id=uuid.uuid4(),
            display_name="Canonical Milk",
            normalized_name="milk",
            brand_display="Brand",
            brand_normalized="brand",
            item_quantity_value=Decimal("500"),
            item_quantity_unit="g",
            pack_count=1,
            gtin14=None,
            category_key=None,
        )
        db.add(product)
        db.flush()

        norm = OfferNormalization(
            id=uuid.uuid4(),
            offer_candidate_id=offer.id,
            normalizer_version="normalizer-v1.1",
            normalized_name="milk",
            normalized_brand="brand",
            item_quantity_value=Decimal("500"),
            item_quantity_unit="g",
            pack_count=1,
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
        return product

    def test_empty_current_deals_is_stable(self) -> None:
        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25"
        ).json()
        self.assertEqual(body["available_count"], 0)
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["deals"], [])
        self.assertEqual(body["retailer_counts"], {})

    def test_current_validity_is_inclusive_and_unknown_excluded(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            snapshot = self.snapshot("edeka", at)
            db.add(snapshot)
            db.add_all(
                [
                    self.offer(
                        snapshot=snapshot,
                        chain="edeka",
                        source_offer_id="active",
                        store="071897",
                        name="Active",
                        brand=None,
                        price="1.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 25),
                        collected_at=at,
                    ),
                    self.offer(
                        snapshot=snapshot,
                        chain="edeka",
                        source_offer_id="future",
                        store="071897",
                        name="Future",
                        brand=None,
                        price="2.00",
                        valid_from=date(2026, 7, 26),
                        valid_until=date(2026, 7, 30),
                        collected_at=at,
                    ),
                    self.offer(
                        snapshot=snapshot,
                        chain="edeka",
                        source_offer_id="unknown",
                        store="071897",
                        name="Unknown",
                        brand=None,
                        price="3.00",
                        valid_from=None,
                        valid_until=None,
                        collected_at=at,
                    ),
                ]
            )

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25"
        ).json()
        self.assertEqual(body["available_count"], 1)
        self.assertEqual(body["deals"][0]["product_name_raw"], "Active")

    def test_repeated_snapshot_identity_collapses_to_newest(self) -> None:
        older = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s1 = self.snapshot("edeka", older)
            s2 = self.snapshot("edeka", newer)
            db.add_all([s1, s2])
            db.add_all(
                [
                    self.offer(
                        snapshot=s1,
                        chain="edeka",
                        source_offer_id="same",
                        store="071897",
                        name="Milk old",
                        brand="Brand",
                        price="2.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=older,
                    ),
                    self.offer(
                        snapshot=s2,
                        chain="edeka",
                        source_offer_id="same",
                        store="071897",
                        name="Milk new",
                        brand="Brand",
                        price="1.80",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=newer,
                    ),
                ]
            )

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25"
        ).json()
        self.assertEqual(body["available_count"], 1)
        self.assertEqual(body["deals"][0]["product_name_raw"], "Milk new")
        self.assertEqual(body["deals"][0]["price_eur"], "1.80")

    def test_store_scope_is_part_of_dedup_identity(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            snapshot_a = self.snapshot("edeka", at)
            snapshot_b = self.snapshot("edeka", at)
            db.add_all([snapshot_a, snapshot_b])
            db.add_all(
                [
                    self.offer(
                        snapshot=snapshot_a,
                        chain="edeka",
                        source_offer_id="same",
                        store="111",
                        name="Milk A",
                        brand=None,
                        price="1.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=at,
                    ),
                    self.offer(
                        snapshot=snapshot_b,
                        chain="edeka",
                        source_offer_id="same",
                        store="222",
                        name="Milk B",
                        brand=None,
                        price="1.10",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=at,
                    ),
                ]
            )

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25"
        ).json()
        self.assertEqual(body["available_count"], 2)
        self.assertEqual(
            {deal["source_store_external_id"] for deal in body["deals"]},
            {"111", "222"},
        )

    def test_search_matches_brand_or_name(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            snapshot = self.snapshot("aldi_nord", at)
            db.add(snapshot)
            db.add(
                self.offer(
                    snapshot=snapshot,
                    chain="aldi_nord",
                    source_offer_id="milk",
                    store=None,
                    name="Haferdrink",
                    brand="Oatly",
                    price="1.79",
                    valid_from=date(2026, 7, 25),
                    valid_until=date(2026, 7, 31),
                    collected_at=at,
                )
            )

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25&q=oatly"
        ).json()
        self.assertEqual(body["available_count"], 1)
        self.assertEqual(body["deals"][0]["product_name_raw"], "Haferdrink")

    def test_retailer_filter_and_counts(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            edeka = self.snapshot("edeka", at)
            aldi = self.snapshot("aldi_nord", at)
            db.add_all([edeka, aldi])
            db.add_all(
                [
                    self.offer(
                        snapshot=edeka,
                        chain="edeka",
                        source_offer_id="e1",
                        store="071897",
                        name="One",
                        brand=None,
                        price="1.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=at,
                    ),
                    self.offer(
                        snapshot=aldi,
                        chain="aldi_nord",
                        source_offer_id="a1",
                        store=None,
                        name="Two",
                        brand=None,
                        price="2.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=at,
                    ),
                ]
            )

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25&retailer=edeka"
        ).json()
        self.assertEqual(body["available_count"], 1)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["deals"][0]["source_chain"], "edeka")
        self.assertEqual(body["retailer_counts"], {"aldi_nord": 1, "edeka": 1})

    def test_price_sort_is_stable(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            snapshot = self.snapshot("edeka", at)
            db.add(snapshot)
            db.add_all(
                [
                    self.offer(
                        snapshot=snapshot,
                        chain="edeka",
                        source_offer_id="expensive",
                        store="071897",
                        name="Expensive",
                        brand=None,
                        price="5.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=at,
                    ),
                    self.offer(
                        snapshot=snapshot,
                        chain="edeka",
                        source_offer_id="cheap",
                        store="071897",
                        name="Cheap",
                        brand=None,
                        price="1.00",
                        valid_from=date(2026, 7, 25),
                        valid_until=date(2026, 7, 31),
                        collected_at=at,
                    ),
                ]
            )

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25&sort=price_asc"
        ).json()
        self.assertEqual(
            [deal["product_name_raw"] for deal in body["deals"]],
            ["Cheap", "Expensive"],
        )

    def test_confirmed_link_exposes_canonical_only_for_linked_observation(self) -> None:
        at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            snapshot = self.snapshot("edeka", at)
            db.add(snapshot)
            linked = self.offer(
                snapshot=snapshot,
                chain="edeka",
                source_offer_id="linked",
                store="071897",
                name="Linked milk",
                brand="Brand",
                price="1.50",
                valid_from=date(2026, 7, 25),
                valid_until=date(2026, 7, 31),
                collected_at=at,
            )
            unlinked = self.offer(
                snapshot=snapshot,
                chain="edeka",
                source_offer_id="unlinked",
                store="071897",
                name="Unlinked milk",
                brand="Brand",
                price="1.60",
                valid_from=date(2026, 7, 25),
                valid_until=date(2026, 7, 31),
                collected_at=at,
            )
            db.add_all([linked, unlinked])
            db.flush()
            product = self.link(db, linked)

        body = self.client.get(
            "/api/v1/deals/current?as_of=2026-07-25"
        ).json()
        by_name = {deal["product_name_raw"]: deal for deal in body["deals"]}
        self.assertTrue(by_name["Linked milk"]["canonical_comparable"])
        self.assertEqual(
            by_name["Linked milk"]["canonical_product_id"],
            str(product.id),
        )
        self.assertFalse(by_name["Unlinked milk"]["canonical_comparable"])
        self.assertIsNone(by_name["Unlinked milk"]["canonical_product_id"])

    def test_ui_contains_dual_mode_deals_contract(self) -> None:
        response = self.client.get("/ui")
        self.assertEqual(response.status_code, 200)
        for marker in (
            "/api/v1/deals/current",
            "Aktuālie piedāvājumi",
            "Salīdzināmie produkti",
            "Tikai retailer deal",
            "Canonical salīdzināms",
        ):
            self.assertIn(marker, response.text)


    def test_phase5e_feature_counts(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s=self.snapshot("edeka",at); db.add(s)
            a=self.offer(snapshot=s,chain="edeka",source_offer_id="a",store="071897",name="App",brand=None,price="2.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            a.requires_app=True; a.app_price_eur=Decimal("1.50")
            c=self.offer(snapshot=s,chain="edeka",source_offer_id="c",store="071897",name="Coupon",brand=None,price="3.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            c.coupon_required=True
            d=self.offer(snapshot=s,chain="edeka",source_offer_id="d",store="071897",name="Discount",brand=None,price="4.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            d.regular_price_eur=Decimal("5.00")
            n=self.offer(snapshot=s,chain="edeka",source_offer_id="n",store="071897",name="No image",brand=None,price="6.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            n.source_image_url=None
            db.add_all([a,c,d,n])
        body=self.client.get("/api/v1/deals/current?as_of=2026-07-25").json()
        self.assertEqual(body["feature_counts"]["app"],1)
        self.assertEqual(body["feature_counts"]["coupon"],1)
        self.assertEqual(body["feature_counts"]["discount"],1)
        self.assertEqual(body["feature_counts"]["image"],3)

    def test_phase5e_app_and_coupon_filters_are_and_semantics(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s=self.snapshot("edeka",at); db.add(s)
            both=self.offer(snapshot=s,chain="edeka",source_offer_id="both",store="071897",name="Both",brand=None,price="1.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            both.requires_app=True; both.coupon_required=True
            only=self.offer(snapshot=s,chain="edeka",source_offer_id="only",store="071897",name="Only App",brand=None,price="2.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            only.requires_app=True
            db.add_all([both,only])
        body=self.client.get("/api/v1/deals/current?as_of=2026-07-25&app_only=true&coupon_only=true").json()
        self.assertEqual(body["count"],1)
        self.assertEqual(body["deals"][0]["product_name_raw"],"Both")

    def test_phase5e_discount_filter(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s=self.snapshot("edeka",at); db.add(s)
            d=self.offer(snapshot=s,chain="edeka",source_offer_id="d",store="071897",name="Discount",brand=None,price="4.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            d.regular_price_eur=Decimal("5.00")
            p=self.offer(snapshot=s,chain="edeka",source_offer_id="p",store="071897",name="Plain",brand=None,price="2.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            db.add_all([d,p])
        body=self.client.get("/api/v1/deals/current?as_of=2026-07-25&discount_only=true").json()
        self.assertEqual(body["count"],1)
        self.assertEqual(body["deals"][0]["product_name_raw"],"Discount")

    def test_phase5e_image_filter(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s=self.snapshot("edeka",at); db.add(s)
            a=self.offer(snapshot=s,chain="edeka",source_offer_id="a",store="071897",name="Image",brand=None,price="1.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            b=self.offer(snapshot=s,chain="edeka",source_offer_id="b",store="071897",name="No Image",brand=None,price="2.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            b.source_image_url=None
            db.add_all([a,b])
        body=self.client.get("/api/v1/deals/current?as_of=2026-07-25&image_only=true").json()
        self.assertEqual(body["count"],1)
        self.assertEqual(body["deals"][0]["product_name_raw"],"Image")

    def test_phase5e_discount_desc_sort(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s=self.snapshot("edeka",at); db.add(s)
            small=self.offer(snapshot=s,chain="edeka",source_offer_id="small",store="071897",name="Small",brand=None,price="4.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            small.regular_price_eur=Decimal("5.00")
            large=self.offer(snapshot=s,chain="edeka",source_offer_id="large",store="071897",name="Large",brand=None,price="3.00",valid_from=date(2026,7,25),valid_until=date(2026,7,31),collected_at=at)
            large.regular_price_eur=Decimal("6.00")
            db.add_all([small,large])
        body=self.client.get("/api/v1/deals/current?as_of=2026-07-25&sort=discount_desc").json()
        self.assertEqual([x["product_name_raw"] for x in body["deals"]],["Large","Small"])

    def test_phase5e_ui_daily_use_contract(self) -> None:
        response=self.client.get("/ui")
        self.assertEqual(response.status_code,200)
        for marker in ('data-feature="app"','data-feature="coupon"','data-feature="discount"','data-feature="image"',"discount_desc","quickDates","restoreUrl","syncUrl","Piedāvājuma detaļas"):
            self.assertIn(marker,response.text)


    def test_phase5f_latest_snapshot_availability_is_separate_from_current_deals(self) -> None:
        at=datetime(2026,7,25,8,0,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            edeka=self.snapshot("edeka",at)
            aldi=self.snapshot("aldi_nord",at)
            netto=self.snapshot("netto",at)
            lidl=self.snapshot("lidl",at)
            db.add_all([edeka,aldi,netto,lidl])
            db.add_all([
                self.offer(snapshot=edeka,chain="edeka",source_offer_id="current-5f",store="071897",name="Current 5F",brand=None,price="1.00",valid_from=date(2026,7,25),valid_until=date(2026,7,25),collected_at=at),
                self.offer(snapshot=aldi,chain="aldi_nord",source_offer_id="future-5f",store=None,name="Future 5F",brand=None,price="2.00",valid_from=date(2026,8,1),valid_until=date(2026,8,1),collected_at=at),
                self.offer(snapshot=netto,chain="netto",source_offer_id="unknown-5f",store="5659",name="Unknown 5F",brand=None,price="3.00",valid_from=None,valid_until=None,collected_at=at),
                self.offer(snapshot=lidl,chain="lidl",source_offer_id="expired-5f",store=None,name="Expired 5F",brand=None,price="4.00",valid_from=date(2026,7,1),valid_until=date(2026,7,2),collected_at=at),
            ])

        with patch("app.main._active_source_config", return_value=None):
            body=self.client.get("/api/v1/deals/current?as_of=2026-07-25").json()

        self.assertEqual(body["count"],1)
        self.assertEqual(body["deals"][0]["product_name_raw"],"Current 5F")
        self.assertEqual(
            body["availability_counts"],
            {"current":1,"upcoming":1,"unknown":1,"expired":1},
        )
        self.assertEqual(body["retailer_availability"]["edeka"]["current"],1)
        self.assertEqual(body["retailer_availability"]["aldi_nord"]["upcoming"],1)
        self.assertEqual(body["retailer_availability"]["netto"]["unknown"],1)
        self.assertEqual(body["retailer_availability"]["lidl"]["expired"],1)

    def test_phase5f_ui_explains_latest_snapshot_availability(self) -> None:
        response=self.client.get("/ui")
        self.assertEqual(response.status_code,200)
        for marker in (
            "availabilityNote",
            'data-offset="7"',
            "retailer_availability",
            "Jaunākie aktīvie bukleti",
            "bez derīguma datuma",
            'id="pagination"',
            "PAGE_SIZE=12",
            "renderDealPage",
            "paginationItems",
        ):
            self.assertIn(marker,response.text)

    def test_phase5g_app_validity_extends_currentness(self) -> None:
        at = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
        with self.Session.begin() as db:
            snapshot = self.snapshot("lidl", at)
            db.add(snapshot)
            offer = self.offer(
                snapshot=snapshot,
                chain="lidl",
                source_offer_id="app-extended",
                store=None,
                name="App extended",
                brand="ESMARA",
                price="9.99",
                valid_from=date(2026, 7, 27),
                valid_until=date(2026, 8, 1),
                collected_at=at,
            )
            offer.app_price_eur = Decimal("7.99")
            offer.requires_app = True
            offer.app_valid_from = date(2026, 7, 27)
            offer.app_valid_until = date(2026, 8, 2)
            db.add(offer)

        on_extension = self.client.get(
            "/api/v1/deals/current?as_of=2026-08-02"
        ).json()
        self.assertEqual(on_extension["available_count"], 1)
        deal = on_extension["deals"][0]
        self.assertEqual(deal["product_name_raw"], "App extended")
        self.assertEqual(deal["price_eur"], "9.99")
        self.assertEqual(deal["app_price_eur"], "7.99")
        self.assertEqual(deal["valid_until"], "2026-08-01")
        self.assertEqual(deal["app_valid_until"], "2026-08-02")
        self.assertFalse(deal["base_price_current"])
        self.assertTrue(deal["app_price_current"])

        after_extension = self.client.get(
            "/api/v1/deals/current?as_of=2026-08-03"
        ).json()
        self.assertEqual(after_extension["available_count"], 0)



if __name__ == "__main__":
    unittest.main()
