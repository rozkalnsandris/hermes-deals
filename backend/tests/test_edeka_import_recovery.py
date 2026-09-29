from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.edeka_collector_cli as cli
from app.edeka_store_offers import EdekaFetchedPage
from app.models import Base, OfferCandidateRecord, SourceSnapshot
from app.source_config import SourceConfig


class EdekaImportRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        engine = create_engine("sqlite+pysqlite:///:memory:")
        self.stack.callback(engine.dispose)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)
        raw_dir = Path(self.stack.enter_context(TemporaryDirectory()))
        source = SourceConfig(
            chain="edeka", enabled=True, priority=2,
            url="https://www.edeka.de/maerkte/071897/angebote/",
            scope="family_primary_edeka", notes="", keywords=("Angebote",),
            store_external_id="071897", store_internal_id="587881",
            store_name="EDEKA Patzer",
        )
        raw = (Path(__file__).parent / "fixtures" / "edeka_weekly_header_offers.html").read_bytes()
        fetched = EdekaFetchedPage(
            final_url=source.url, content=raw, content_type="text/html",
            http_status=200, elapsed_ms=1,
        )
        real_collect = cli.collect_edeka_store_offers

        def collect_with_sqlite_timezone(db, source):
            result = real_collect(db, source)
            # SQLite drops timezone metadata on refresh; production PostgreSQL
            # preserves timestamptz. Adapt only this test database boundary.
            if result.snapshot.collected_at.tzinfo is None:
                result.snapshot.collected_at = result.snapshot.collected_at.replace(tzinfo=timezone.utc)
            return result

        for mocked in (
            patch.object(cli, "SessionLocal", self.sessions),
            patch.object(cli, "_edeka_source", return_value=source),
            patch.object(cli, "collect_edeka_store_offers", side_effect=collect_with_sqlite_timezone),
            patch("app.edeka_store_offers.fetch_edeka_store_offers", return_value=fetched),
            patch("app.edeka_store_offers.get_settings", return_value=SimpleNamespace(raw_snapshot_dir=raw_dir)),
            patch("app.edeka_store_offers._utc_now", return_value=datetime(2026, 9, 29, 9, tzinfo=timezone.utc)),
            patch("app.edeka_store_offers.parser_identity_from_environment", return_value=None),
        ):
            self.stack.enter_context(mocked)

    def counts(self):
        with self.sessions() as db:
            return (
                db.scalar(select(func.count()).select_from(SourceSnapshot)),
                db.scalar(select(func.count()).select_from(OfferCandidateRecord)),
            )

    def test_recovers_after_minimum_gate_without_duplicate_snapshot(self):
        self.assertEqual(cli.collect_edeka(3), 3)
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(cli.collect_edeka(2), 0)
        self.assertEqual(self.counts(), (1, 2))
        self.assertEqual(cli.collect_edeka(2), 0)
        self.assertEqual(self.counts(), (1, 2))

    def test_recovers_after_offer_write_failure(self):
        with patch.object(cli, "save_offer_candidates", side_effect=RuntimeError("write failed")):
            with self.assertRaisesRegex(RuntimeError, "write failed"):
                cli.collect_edeka(2)
        self.assertEqual(self.counts(), (1, 0))
        self.assertEqual(cli.collect_edeka(2), 0)
        self.assertEqual(self.counts(), (1, 2))

    def test_unchanged_source_still_enforces_minimum_gate(self):
        self.assertEqual(cli.collect_edeka(3), 3)
        self.assertEqual(cli.collect_edeka(3), 3)
        self.assertEqual(self.counts(), (1, 0))

    def test_unchanged_source_rejects_partial_persisted_set(self):
        self.assertEqual(cli.collect_edeka(2), 0)
        with self.sessions() as db:
            db.delete(db.scalar(select(OfferCandidateRecord)))
            db.commit()
        with self.assertRaisesRegex(ValueError, "source_offer_id set"):
            cli.collect_edeka(2)
        self.assertEqual(self.counts(), (1, 1))

    def test_unchanged_source_rejects_changed_persisted_payload(self):
        self.assertEqual(cli.collect_edeka(2), 0)
        with self.sessions() as db:
            db.scalar(select(OfferCandidateRecord)).price_eur += Decimal("1.00")
            db.commit()
        with self.assertRaisesRegex(ValueError, "differs from incoming"):
            cli.collect_edeka(2)
        self.assertEqual(self.counts(), (1, 2))
