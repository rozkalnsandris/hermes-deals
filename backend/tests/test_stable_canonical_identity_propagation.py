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


class StableCanonicalIdentityPropagationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine=create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread":False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self.Session=sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

        def override_get_db():
            db=self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db]=override_get_db
        self.client=TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.engine.dispose()

    @staticmethod
    def snapshot(chain: str, when: datetime) -> SourceSnapshot:
        return SourceSnapshot(
            id=uuid.uuid4(),
            source_chain=chain,
            source_url=f"https://example.invalid/{chain}/{when.timestamp()}",
            final_url=None,
            scope=None,
            collected_at=when,
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
        store: str | None,
        source_offer_id: str,
        name: str,
        price: str,
        when: datetime,
    ) -> OfferCandidateRecord:
        return OfferCandidateRecord(
            id=uuid.uuid4(),
            source_chain=chain,
            source_store_external_id=store,
            source_store_name=None,
            source_offer_id=source_offer_id,
            product_name_raw=name,
            brand_raw="TEST",
            description_raw=None,
            package_text_raw="1 L",
            price_eur=Decimal(price),
            regular_price_eur=None,
            unit_price_eur=None,
            unit_label=None,
            discount_percent=None,
            app_price_eur=None,
            requires_app=False,
            coupon_required=False,
            valid_from=date(2026,7,30),
            valid_until=date(2026,7,30),
            source_url="https://example.invalid/offer",
            source_image_url=None,
            snapshot_id=snapshot.id,
            collected_at=when,
            parser_version="test-v1",
            raw_payload={},
        )

    @staticmethod
    def product(db: Session, name: str) -> CanonicalProduct:
        row=CanonicalProduct(
            id=uuid.uuid4(),
            display_name=name,
            normalized_name=name.casefold(),
            brand_display="Test",
            brand_normalized="test",
            item_quantity_value=Decimal("1000"),
            item_quantity_unit="ml",
            pack_count=1,
            gtin14=None,
            category_key=None,
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def link(
        db: Session,
        product: CanonicalProduct,
        offer: OfferCandidateRecord,
    ) -> None:
        norm=OfferNormalization(
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
        candidate=ProductMatchCandidate(
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

    def test_newer_snapshot_inherits_unambiguous_stable_identity(self) -> None:
        old_at=datetime(2026,7,29,8,tzinfo=timezone.utc)
        new_at=datetime(2026,7,30,8,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s_old=self.snapshot("edeka",old_at)
            s_new=self.snapshot("edeka",new_at)
            db.add_all([s_old,s_new])
            old=self.offer(
                snapshot=s_old,
                chain="edeka",
                store="071897",
                source_offer_id="stable-1",
                name="Stable old",
                price="1.99",
                when=old_at,
            )
            new=self.offer(
                snapshot=s_new,
                chain="edeka",
                store="071897",
                source_offer_id="stable-1",
                name="Stable new",
                price="1.79",
                when=new_at,
            )
            db.add_all([old,new])
            db.flush()
            product=self.product(db,"Stable product")
            self.link(db,product,old)
            product_id=str(product.id)
            new_id=str(new.id)

        body=self.client.get(
            "/api/v1/deals/current?as_of=2026-07-30&limit=500"
        ).json()
        rows=[
            row for row in body["deals"]
            if row["source_offer_id"]=="stable-1"
            and row["source_store_external_id"]=="071897"
        ]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["offer_candidate_id"],new_id)
        self.assertEqual(rows[0]["canonical_product_id"],product_id)
        self.assertTrue(rows[0]["canonical_comparable"])

    def test_store_is_part_of_stable_identity(self) -> None:
        old_at=datetime(2026,7,29,8,tzinfo=timezone.utc)
        new_at=datetime(2026,7,30,8,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s_old=self.snapshot("netto",old_at)
            s_new=self.snapshot("netto",new_at)
            # A single source snapshot cannot contain two rows with the same
            # source_offer_id because persistence is immutable and enforces
            # UNIQUE(snapshot_id, source_offer_id). Use a separate snapshot for
            # the second store so this fixture tests store isolation instead of
            # violating the persistence contract.
            s_other=self.snapshot(
                "netto",
                new_at.replace(second=1),
            )
            db.add_all([s_old,s_new,s_other])
            linked_old=self.offer(
                snapshot=s_old,
                chain="netto",
                store="5659",
                source_offer_id="same-id",
                name="Linked store old",
                price="1.00",
                when=old_at,
            )
            linked_new=self.offer(
                snapshot=s_new,
                chain="netto",
                store="5659",
                source_offer_id="same-id",
                name="Linked store new",
                price="0.90",
                when=new_at,
            )
            other_store=self.offer(
                snapshot=s_other,
                chain="netto",
                store="6071",
                source_offer_id="same-id",
                name="Other store",
                price="0.80",
                when=new_at,
            )
            db.add_all([linked_old,linked_new,other_store])
            db.flush()
            product=self.product(db,"Store-bound product")
            self.link(db,product,linked_old)
            product_id=str(product.id)

        body=self.client.get(
            "/api/v1/deals/current?as_of=2026-07-30&limit=500"
        ).json()
        rows={
            row["source_store_external_id"]:row
            for row in body["deals"]
            if row["source_offer_id"]=="same-id"
        }
        self.assertEqual(rows["5659"]["canonical_product_id"],product_id)
        self.assertTrue(rows["5659"]["canonical_comparable"])
        self.assertIsNone(rows["6071"]["canonical_product_id"])
        self.assertFalse(rows["6071"]["canonical_comparable"])

    def test_ambiguous_stable_identity_fails_closed(self) -> None:
        t1=datetime(2026,7,28,8,tzinfo=timezone.utc)
        t2=datetime(2026,7,29,8,tzinfo=timezone.utc)
        t3=datetime(2026,7,30,8,tzinfo=timezone.utc)
        with self.Session.begin() as db:
            s1=self.snapshot("aldi_nord",t1)
            s2=self.snapshot("aldi_nord",t2)
            s3=self.snapshot("aldi_nord",t3)
            db.add_all([s1,s2,s3])
            old1=self.offer(
                snapshot=s1,
                chain="aldi_nord",
                store=None,
                source_offer_id="ambiguous-id",
                name="Ambiguous first",
                price="2.00",
                when=t1,
            )
            old2=self.offer(
                snapshot=s2,
                chain="aldi_nord",
                store=None,
                source_offer_id="ambiguous-id",
                name="Ambiguous second",
                price="1.90",
                when=t2,
            )
            newest=self.offer(
                snapshot=s3,
                chain="aldi_nord",
                store=None,
                source_offer_id="ambiguous-id",
                name="Ambiguous newest",
                price="1.80",
                when=t3,
            )
            db.add_all([old1,old2,newest])
            db.flush()
            p1=self.product(db,"Canonical one")
            p2=self.product(db,"Canonical two")
            self.link(db,p1,old1)
            self.link(db,p2,old2)
            newest_id=str(newest.id)

        body=self.client.get(
            "/api/v1/deals/current?as_of=2026-07-30&limit=500"
        ).json()
        rows=[
            row for row in body["deals"]
            if row["source_offer_id"]=="ambiguous-id"
        ]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["offer_candidate_id"],newest_id)
        self.assertIsNone(rows[0]["canonical_product_id"])
        self.assertFalse(rows[0]["canonical_comparable"])


if __name__=="__main__":
    unittest.main()
