from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Base,
    CanonicalProduct,
    OfferCandidateRecord,
    OfferNormalization,
    OfferProductLink,
    ProductMatchCandidate,
    SourceSnapshot,
)


class ProductIdentityModelTest(unittest.TestCase):
    def _engine(self):
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        self.addCleanup(engine.dispose)

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        return engine

    def _seed_offer(self, db: Session, suffix: str) -> OfferCandidateRecord:
        snapshot = SourceSnapshot(
            id=uuid4(),
            source_chain="aldi_nord",
            source_url=f"https://example.test/source/{suffix}",
            final_url=f"https://example.test/source/{suffix}",
            scope="fixture",
            collected_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            http_status=200,
            elapsed_ms=1,
            content_type="application/json",
            content_bytes=2,
            sha256=("a" if suffix == "a" else "b") * 64,
            snapshot_path=f"/tmp/{suffix}.json",
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint="fixture",
            success=True,
            error=None,
        )
        db.add(snapshot)
        db.flush()

        offer = OfferCandidateRecord(
            id=uuid4(),
            source_chain="aldi_nord",
            source_store_external_id=None,
            source_store_name="ALDI Nord",
            source_offer_id=f"fixture:{suffix}",
            product_name_raw=f"Product {suffix}",
            brand_raw="Brand",
            description_raw=None,
            package_text_raw="100 g",
            price_eur=Decimal("1.00"),
            regular_price_eur=None,
            unit_price_eur=Decimal("10.0000"),
            unit_label="kg",
            discount_percent=None,
            app_price_eur=None,
            requires_app=False,
            coupon_required=False,
            valid_from=None,
            valid_until=None,
            source_url=f"https://example.test/offer/{suffix}",
            source_image_url=None,
            snapshot_id=snapshot.id,
            collected_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
            parser_version="fixture",
            raw_payload={},
        )
        db.add(offer)
        db.flush()
        return offer

    def _normalization(
        self,
        db: Session,
        offer: OfferCandidateRecord,
        version: str = "normalizer-v1",
    ) -> OfferNormalization:
        row = OfferNormalization(
            offer_candidate_id=offer.id,
            normalizer_version=version,
            normalized_name=offer.product_name_raw.casefold(),
            normalized_brand="brand",
            item_quantity_value=Decimal("100.0000"),
            item_quantity_unit="g",
            pack_count=1,
            gtin14=None,
            category_key=None,
            evidence_json={"fixture": True},
        )
        db.add(row)
        db.flush()
        return row

    def _product(
        self,
        db: Session,
        name: str,
        gtin14: str | None = None,
    ) -> CanonicalProduct:
        row = CanonicalProduct(
            display_name=name,
            normalized_name=name.casefold(),
            brand_display="Brand",
            brand_normalized="brand",
            item_quantity_value=Decimal("100.0000"),
            item_quantity_unit="g",
            pack_count=1,
            gtin14=gtin14,
            category_key=None,
        )
        db.add(row)
        db.flush()
        return row

    def _candidate(
        self,
        db: Session,
        offer: OfferCandidateRecord,
        normalization: OfferNormalization,
        product: CanonicalProduct,
        matcher_version: str = "matcher-v1",
        status: str = "pending",
    ) -> ProductMatchCandidate:
        row = ProductMatchCandidate(
            offer_candidate_id=offer.id,
            offer_normalization_id=normalization.id,
            canonical_product_id=product.id,
            matcher_version=matcher_version,
            match_method="exact_name_brand_package",
            confidence=Decimal("0.9500"),
            evidence_json={"fixture": True},
            review_status=status,
            decision_reason="fixture" if status != "pending" else None,
            decided_at=(
                datetime(2026, 7, 25, tzinfo=timezone.utc)
                if status != "pending"
                else None
            ),
        )
        db.add(row)
        db.flush()
        return row

    def test_four_phase3_tables_exist_in_metadata(self) -> None:
        self.assertIn("offer_normalizations", Base.metadata.tables)
        self.assertIn("canonical_products", Base.metadata.tables)
        self.assertIn("product_match_candidates", Base.metadata.tables)
        self.assertIn("offer_product_links", Base.metadata.tables)

    def test_normalization_is_versioned_per_offer(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            self._normalization(db, offer)
            db.commit()
            db.add(
                OfferNormalization(
                    offer_candidate_id=offer.id,
                    normalizer_version="normalizer-v1",
                    normalized_name="different",
                    evidence_json={},
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_same_offer_can_have_multiple_normalizer_versions(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            self._normalization(db, offer, "normalizer-v1")
            self._normalization(db, offer, "normalizer-v2")
            db.commit()

    def test_normalization_rejects_nonpositive_package_values(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            db.add(
                OfferNormalization(
                    offer_candidate_id=offer.id,
                    normalizer_version="normalizer-v1",
                    normalized_name="product",
                    item_quantity_value=Decimal("0"),
                    pack_count=0,
                    evidence_json={},
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_canonical_gtin14_is_unique_when_present(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            self._product(db, "First", "04012345678901")
            db.commit()
            db.add(
                CanonicalProduct(
                    display_name="Second",
                    normalized_name="second",
                    gtin14="04012345678901",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_canonical_gtin14_requires_length_14(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            db.add(
                CanonicalProduct(
                    display_name="Bad GTIN",
                    normalized_name="bad gtin",
                    gtin14="1234567890123",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_one_normalized_offer_can_keep_multiple_product_candidates(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            normalization = self._normalization(db, offer)
            first = self._product(db, "Product A")
            second = self._product(db, "Product B")
            self._candidate(db, offer, normalization, first)
            self._candidate(db, offer, normalization, second)
            db.commit()

    def test_duplicate_candidate_for_same_normalization_product_matcher_is_rejected(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            normalization = self._normalization(db, offer)
            product = self._product(db, "Product")
            self._candidate(db, offer, normalization, product)
            db.commit()

            db.add(
                ProductMatchCandidate(
                    offer_candidate_id=offer.id,
                    offer_normalization_id=normalization.id,
                    canonical_product_id=product.id,
                    matcher_version="matcher-v1",
                    match_method="fuzzy_name",
                    confidence=Decimal("0.8000"),
                    evidence_json={},
                    review_status="pending",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_candidate_cannot_use_normalization_from_another_offer(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer_a = self._seed_offer(db, "a")
            offer_b = self._seed_offer(db, "b")
            normalization_a = self._normalization(db, offer_a)
            product = self._product(db, "Product")
            db.add(
                ProductMatchCandidate(
                    offer_candidate_id=offer_b.id,
                    offer_normalization_id=normalization_a.id,
                    canonical_product_id=product.id,
                    matcher_version="matcher-v1",
                    match_method="fuzzy_name",
                    confidence=Decimal("0.5000"),
                    evidence_json={},
                    review_status="pending",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_candidate_confidence_must_be_zero_to_one(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            normalization = self._normalization(db, offer)
            product = self._product(db, "Product")
            db.add(
                ProductMatchCandidate(
                    offer_candidate_id=offer.id,
                    offer_normalization_id=normalization.id,
                    canonical_product_id=product.id,
                    matcher_version="matcher-v1",
                    match_method="fuzzy_name",
                    confidence=Decimal("1.1000"),
                    evidence_json={},
                    review_status="pending",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_decided_candidate_requires_decided_at_and_pending_requires_null(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            normalization = self._normalization(db, offer)
            product = self._product(db, "Product")
            db.add(
                ProductMatchCandidate(
                    offer_candidate_id=offer.id,
                    offer_normalization_id=normalization.id,
                    canonical_product_id=product.id,
                    matcher_version="matcher-v1",
                    match_method="manual_review",
                    confidence=Decimal("1.0000"),
                    evidence_json={},
                    review_status="accepted",
                    decided_at=None,
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_one_offer_can_have_only_one_confirmed_link(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            first = self._product(db, "Product A")
            second = self._product(db, "Product B")
            db.add(
                OfferProductLink(
                    offer_candidate_id=offer.id,
                    canonical_product_id=first.id,
                    source_match_candidate_id=None,
                    link_method="manual",
                    confidence=Decimal("1.0000"),
                )
            )
            db.commit()

            db.add(
                OfferProductLink(
                    offer_candidate_id=offer.id,
                    canonical_product_id=second.id,
                    source_match_candidate_id=None,
                    link_method="manual",
                    confidence=Decimal("1.0000"),
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_link_source_candidate_must_match_same_offer_and_product(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer_a = self._seed_offer(db, "a")
            offer_b = self._seed_offer(db, "b")
            norm_a = self._normalization(db, offer_a)
            product_a = self._product(db, "Product A")
            product_b = self._product(db, "Product B")
            candidate = self._candidate(
                db,
                offer_a,
                norm_a,
                product_a,
                status="accepted",
            )
            db.commit()

            db.add(
                OfferProductLink(
                    offer_candidate_id=offer_b.id,
                    canonical_product_id=product_b.id,
                    source_match_candidate_id=candidate.id,
                    link_method="reviewed_candidate",
                    confidence=Decimal("0.9500"),
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()

    def test_link_can_reference_matching_accepted_candidate(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            normalization = self._normalization(db, offer)
            product = self._product(db, "Product")
            candidate = self._candidate(
                db,
                offer,
                normalization,
                product,
                status="accepted",
            )
            db.add(
                OfferProductLink(
                    offer_candidate_id=offer.id,
                    canonical_product_id=product.id,
                    source_match_candidate_id=candidate.id,
                    link_method="reviewed_candidate",
                    confidence=Decimal("0.9500"),
                )
            )
            db.commit()

    def test_link_confidence_must_be_zero_to_one(self) -> None:
        engine = self._engine()
        with Session(engine) as db:
            offer = self._seed_offer(db, "a")
            product = self._product(db, "Product")
            db.add(
                OfferProductLink(
                    offer_candidate_id=offer.id,
                    canonical_product_id=product.id,
                    source_match_candidate_id=None,
                    link_method="manual",
                    confidence=Decimal("-0.1000"),
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()


if __name__ == "__main__":
    unittest.main()
