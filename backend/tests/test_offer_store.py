from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, OfferCandidateRecord
from app.offer_store import save_offer_candidates


class _SourceChain:
    value = "netto"


class _Offer:
    source_chain = _SourceChain()

    def __init__(
        self,
        snapshot_id: UUID,
        source_offer_id: str | None,
        name: str,
        price: str = "1.99",
    ) -> None:
        self.snapshot_id = snapshot_id
        self.source_offer_id = source_offer_id
        self.source_url = "https://example.test/netto"
        self.source_image_url = None
        self._name = name
        self._price = price

    def model_dump(self, mode: str = "python") -> dict[str, object]:
        assert mode == "python"
        return {
            "source_chain": "netto",
            "source_store_external_id": "netto-test",
            "source_store_name": "Netto",
            "source_offer_id": self.source_offer_id,
            "product_name_raw": self._name,
            "brand_raw": None,
            "description_raw": None,
            "package_text_raw": None,
            "price_eur": Decimal(self._price),
            "regular_price_eur": None,
            "unit_price_eur": None,
            "unit_label": None,
            "discount_percent": None,
            "app_price_eur": None,
            "requires_app": False,
            "coupon_required": False,
            "valid_from": date(2026, 7, 24),
            "valid_until": date(2026, 7, 30),
            "source_url": self.source_url,
            "source_image_url": None,
            "snapshot_id": self.snapshot_id,
            "collected_at": datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc),
            "parser_version": "test-netto",
            "raw_payload": {},
        }


class OfferStorePersistenceTest(unittest.TestCase):
    def _db(self) -> tuple[object, Session]:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        return engine, Session(engine)

    def test_retry_is_db_level_idempotent(self) -> None:
        engine, db = self._db()
        try:
            snapshot_id = uuid4()
            offers = [
                _Offer(snapshot_id, "offer-1", "One"),
                _Offer(snapshot_id, "offer-2", "Two"),
            ]
            self.assertEqual(save_offer_candidates(db, offers), 2)
            self.assertEqual(save_offer_candidates(db, offers), 0)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
                2,
            )
        finally:
            db.close()
            engine.dispose()

    def test_same_key_with_different_payload_is_rejected(self) -> None:
        engine, db = self._db()
        try:
            snapshot_id = uuid4()
            self.assertEqual(
                save_offer_candidates(
                    db,
                    [_Offer(snapshot_id, "offer-1", "One", "1.99")],
                ),
                1,
            )
            with self.assertRaisesRegex(ValueError, "differs from incoming"):
                save_offer_candidates(
                    db,
                    [_Offer(snapshot_id, "offer-1", "One", "2.49")],
                )
            row = db.scalar(select(OfferCandidateRecord))
            self.assertEqual(row.price_eur, Decimal("1.99"))
        finally:
            db.close()
            engine.dispose()

    def test_duplicate_source_offer_id_in_batch_is_rejected(self) -> None:
        engine, db = self._db()
        try:
            snapshot_id = uuid4()
            offers = [
                _Offer(snapshot_id, "same", "One"),
                _Offer(snapshot_id, "same", "Two"),
            ]
            with self.assertRaisesRegex(ValueError, "Duplicate source_offer_id"):
                save_offer_candidates(db, offers)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
                0,
            )
        finally:
            db.close()
            engine.dispose()

    def test_missing_source_offer_id_is_rejected(self) -> None:
        engine, db = self._db()
        try:
            with self.assertRaisesRegex(
                ValueError,
                "non-empty canonical source_offer_id",
            ):
                save_offer_candidates(db, [_Offer(uuid4(), None, "Missing")])
        finally:
            db.close()
            engine.dispose()

    def test_existing_snapshot_key_set_cannot_be_changed(self) -> None:
        engine, db = self._db()
        try:
            snapshot_id = uuid4()
            self.assertEqual(
                save_offer_candidates(
                    db,
                    [_Offer(snapshot_id, "offer-1", "One")],
                ),
                1,
            )
            with self.assertRaisesRegex(ValueError, "do not exactly match"):
                save_offer_candidates(
                    db,
                    [
                        _Offer(snapshot_id, "offer-1", "One"),
                        _Offer(snapshot_id, "offer-2", "Two"),
                    ],
                )
            self.assertEqual(
                db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
                1,
            )
        finally:
            db.close()
            engine.dispose()

    def test_orm_unique_constraint_blocks_same_snapshot_offer_key(self) -> None:
        engine, db = self._db()
        try:
            snapshot_id = uuid4()
            common = {
                "source_chain": "netto",
                "source_offer_id": "same",
                "product_name_raw": "Product",
                "price_eur": Decimal("1.00"),
                "source_url": "https://example.test",
                "snapshot_id": snapshot_id,
                "collected_at": datetime(
                    2026,
                    7,
                    24,
                    8,
                    0,
                    tzinfo=timezone.utc,
                ),
                "parser_version": "test",
                "raw_payload": {},
            }
            db.add_all(
                [
                    OfferCandidateRecord(id=uuid4(), **common),
                    OfferCandidateRecord(id=uuid4(), **common),
                ]
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
