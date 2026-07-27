from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.main import latest_offers, latest_sources
from app.models import Base, OfferCandidateRecord, SourceSnapshot
from app.schemas import SourceChain


class ApiStoreScopeIsolationTest(unittest.TestCase):
    def _db(self) -> tuple[object, Session]:
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        return engine, Session(engine)

    @staticmethod
    def _snapshot(
        *,
        snapshot_id,
        chain: str,
        scope: str,
        collected_at: datetime,
    ) -> SourceSnapshot:
        return SourceSnapshot(
            id=snapshot_id,
            source_chain=chain,
            source_url=f"https://example.test/{scope}",
            final_url=f"https://example.test/{scope}",
            scope=scope,
            collected_at=collected_at,
            strategy_hint="scope-test",
            success=True,
        )

    @staticmethod
    def _offer(
        *,
        snapshot_id,
        chain: str,
        store_id: str | None,
        name: str,
        collected_at: datetime,
    ) -> OfferCandidateRecord:
        return OfferCandidateRecord(
            id=uuid4(),
            source_chain=chain,
            source_store_external_id=store_id,
            source_store_name=(
                f"Store {store_id}" if store_id is not None else "Lidl"
            ),
            source_offer_id=f"{chain}-{store_id}-{name}",
            product_name_raw=name,
            price_eur=Decimal("1.99"),
            source_url="https://example.test/offers",
            snapshot_id=snapshot_id,
            collected_at=collected_at,
            parser_version="scope-test",
            raw_payload={},
        )

    def test_latest_netto_offers_ignore_newer_historical_other_store(self) -> None:
        engine, db = self._db()
        try:
            now = datetime.now(timezone.utc)
            active_snapshot = uuid4()
            historical_snapshot = uuid4()

            db.add_all(
                [
                    self._snapshot(
                        snapshot_id=active_snapshot,
                        chain="netto",
                        scope="family_primary_netto",
                        collected_at=now,
                    ),
                    self._snapshot(
                        snapshot_id=historical_snapshot,
                        chain="netto",
                        scope="sample_dortmund_store",
                        collected_at=now + timedelta(hours=1),
                    ),
                    self._offer(
                        snapshot_id=active_snapshot,
                        chain="netto",
                        store_id="5659",
                        name="Active",
                        collected_at=now,
                    ),
                    self._offer(
                        snapshot_id=historical_snapshot,
                        chain="netto",
                        store_id="6071",
                        name="Historical",
                        collected_at=now + timedelta(hours=1),
                    ),
                ]
            )
            db.commit()

            active = SimpleNamespace(
                store_external_id="5659",
                scope="family_primary_netto",
            )
            with patch("app.main._active_source_config", return_value=active):
                rows = latest_offers(SourceChain.NETTO, limit=100, db=db)

            self.assertEqual([row.product_name_raw for row in rows], ["Active"])
            self.assertEqual(rows[0].source_store_external_id, "5659")
        finally:
            db.close()
            engine.dispose()

    def test_latest_sources_uses_active_store_scope_for_netto(self) -> None:
        engine, db = self._db()
        try:
            now = datetime.now(timezone.utc)
            active_snapshot = uuid4()
            historical_snapshot = uuid4()

            db.add_all(
                [
                    self._snapshot(
                        snapshot_id=active_snapshot,
                        chain="netto",
                        scope="family_primary_netto",
                        collected_at=now,
                    ),
                    self._snapshot(
                        snapshot_id=historical_snapshot,
                        chain="netto",
                        scope="sample_dortmund_store",
                        collected_at=now + timedelta(hours=1),
                    ),
                ]
            )
            db.commit()

            active = SimpleNamespace(
                store_external_id="5659",
                scope="family_primary_netto",
            )

            def configured(chain: SourceChain):
                return active if chain == SourceChain.NETTO else None

            with patch("app.main._active_source_config", side_effect=configured):
                rows = latest_sources(db=db)

            netto = [row for row in rows if row.source_chain == "netto"]
            self.assertEqual(len(netto), 1)
            self.assertEqual(netto[0].id, active_snapshot)
            self.assertEqual(netto[0].scope, "family_primary_netto")
        finally:
            db.close()
            engine.dispose()

    def test_unscoped_lidl_keeps_latest_by_chain_behavior(self) -> None:
        engine, db = self._db()
        try:
            now = datetime.now(timezone.utc)
            older = uuid4()
            newer = uuid4()
            db.add_all(
                [
                    self._snapshot(
                        snapshot_id=older,
                        chain="lidl",
                        scope="older",
                        collected_at=now,
                    ),
                    self._snapshot(
                        snapshot_id=newer,
                        chain="lidl",
                        scope="newer",
                        collected_at=now + timedelta(hours=1),
                    ),
                    self._offer(
                        snapshot_id=older,
                        chain="lidl",
                        store_id=None,
                        name="Older",
                        collected_at=now,
                    ),
                    self._offer(
                        snapshot_id=newer,
                        chain="lidl",
                        store_id=None,
                        name="Newer",
                        collected_at=now + timedelta(hours=1),
                    ),
                ]
            )
            db.commit()

            with patch("app.main._active_source_config", return_value=None):
                rows = latest_offers(SourceChain.LIDL, limit=100, db=db)

            self.assertEqual([row.product_name_raw for row in rows], ["Newer"])
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
