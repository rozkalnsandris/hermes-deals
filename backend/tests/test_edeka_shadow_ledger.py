from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.edeka_shadow_ledger import (
    build_two_cycle_shadow_ledger,
    write_shadow_ledger,
)
from app.edeka_store_offers import (
    EdekaFetchedPage,
    MANIFEST_CONTENT_TYPE,
    MANIFEST_STRATEGY,
    _write_manifest,
    parse_edeka_store_offers_snapshot,
)
from app.models import Base, OfferCandidateRecord, SourceSnapshot
from app.offer_store import save_offer_candidates
from app.parsers.edeka import EdekaParserContext, parse_edeka_html
from app.source_config import SourceConfig


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
SNAPSHOT_ONE = UUID("11111111-2222-4333-8444-555555555551")
SNAPSHOT_TWO = UUID("11111111-2222-4333-8444-555555555552")
COLLECTED_ONE = datetime(2026, 8, 3, 5, 15, tzinfo=timezone.utc)
COLLECTED_TWO = datetime(2026, 8, 11, 5, 15, tzinfo=timezone.utc)


def _source() -> SourceConfig:
    return SourceConfig(
        chain="edeka",
        enabled=True,
        priority=2,
        url=SOURCE_URL,
        scope="family_primary_edeka",
        notes="",
        keywords=("Angebote",),
        store_external_id="071897",
        store_internal_id="587881",
        store_name="EDEKA Patzer",
    )


def _context(snapshot_id: UUID, collected_at: datetime) -> EdekaParserContext:
    return EdekaParserContext(
        snapshot_id=snapshot_id,
        source_url=SOURCE_URL,
        collected_at=collected_at,
        public_market_id="071897",
        internal_market_id="587881",
        store_name="EDEKA Patzer",
    )


def _html(valid_from: str, valid_until: str) -> bytes:
    return (
        FIXTURE.read_text(encoding="utf-8")
        .replace("20.07.2026", valid_from)
        .replace("25.07.2026", valid_until)
        .encode("utf-8")
    )


def _create_manifest(
    root: Path,
    *,
    snapshot_id: UUID,
    collected_at: datetime,
    valid_from: str,
    valid_until: str,
):
    content = _html(valid_from, valid_until)
    fetched = EdekaFetchedPage(
        final_url=SOURCE_URL,
        content=content,
        content_type="text/html; charset=utf-8",
        http_status=200,
        elapsed_ms=1,
    )
    context = _context(snapshot_id, collected_at)
    offers = parse_edeka_html(content, context)
    with patch(
        "app.edeka_store_offers.get_settings",
        return_value=SimpleNamespace(raw_snapshot_dir=root),
    ):
        path, digest = _write_manifest(
            source=_source(),
            snapshot_id=snapshot_id,
            collected_at=collected_at,
            fetched=fetched,
            offers=offers,
        )
    return path, digest, offers, content


def _two_cycles(root: Path):
    first = _create_manifest(
        root,
        snapshot_id=SNAPSHOT_ONE,
        collected_at=COLLECTED_ONE,
        valid_from="03.08.2026",
        valid_until="08.08.2026",
    )
    second = _create_manifest(
        root,
        snapshot_id=SNAPSHOT_TWO,
        collected_at=COLLECTED_TWO,
        valid_from="10.08.2026",
        valid_until="15.08.2026",
    )
    return first, second


class EdekaTwoCycleShadowLedgerTest(unittest.TestCase):
    def test_two_consecutive_cycles_produce_deterministic_pass_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = _two_cycles(Path(temporary))
            ledger = build_two_cycle_shadow_ledger(
                (first[0], first[1]),
                (second[0], second[1]),
                min_offers_per_cycle=1,
            )

        self.assertEqual(ledger["result"], "pass")
        self.assertEqual(len(ledger["cycles"]), 2)
        self.assertEqual(ledger["cycles"][0]["valid_from"], "2026-08-03")
        self.assertEqual(ledger["cycles"][1]["valid_from"], "2026-08-10")
        self.assertEqual(ledger["delta"]["added_count"], 0)
        self.assertEqual(ledger["delta"]["removed_count"], 0)
        self.assertEqual(ledger["delta"]["retention_percent"], "100.00")
        self.assertFalse(ledger["delta"]["unexplained_data_loss"])
        self.assertEqual(
            ledger["replay_contract"][
                "same_snapshot_replay_expected_offer_delta"
            ],
            0,
        )
        self.assertTrue(
            ledger["replay_contract"]["subset_snapshot_persistence_forbidden"]
        )
        self.assertEqual(len(ledger["ledger_sha256"]), 64)

    def test_cycle_order_and_exact_week_gap_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _create_manifest(
                root,
                snapshot_id=SNAPSHOT_ONE,
                collected_at=COLLECTED_ONE,
                valid_from="03.08.2026",
                valid_until="08.08.2026",
            )
            late = _create_manifest(
                root,
                snapshot_id=SNAPSHOT_TWO,
                collected_at=COLLECTED_TWO,
                valid_from="11.08.2026",
                valid_until="16.08.2026",
            )
            with self.assertRaisesRegex(ValueError, "seven days"):
                build_two_cycle_shadow_ledger(
                    (first[0], first[1]),
                    (late[0], late[1]),
                    min_offers_per_cycle=1,
                )

            with self.assertRaisesRegex(ValueError, "seven days"):
                build_two_cycle_shadow_ledger(
                    (late[0], late[1]),
                    (first[0], first[1]),
                    min_offers_per_cycle=1,
                )

    def test_minimum_offer_gate_rejects_fixture_as_production_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = _two_cycles(Path(temporary))
            with self.assertRaisesRegex(ValueError, "minimum is 150"):
                build_two_cycle_shadow_ledger(
                    (first[0], first[1]),
                    (second[0], second[1]),
                )

    def test_writer_is_idempotent_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = _two_cycles(root)
            ledger = build_two_cycle_shadow_ledger(
                (first[0], first[1]),
                (second[0], second[1]),
                min_offers_per_cycle=1,
                max_offer_count_drop_percent=Decimal("0.00"),
            )
            path = root / "ledger.json"
            write_shadow_ledger(path, ledger)
            original = path.read_bytes()
            write_shadow_ledger(path, ledger)
            self.assertEqual(path.read_bytes(), original)

            changed = dict(ledger)
            changed["ledger_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "different"):
                write_shadow_ledger(path, changed)

    def test_tampered_manifest_is_rejected_before_shadow_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = _two_cycles(Path(temporary))
            second[0].write_bytes(second[0].read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "manifest SHA mismatch"):
                build_two_cycle_shadow_ledger(
                    (first[0], first[1]),
                    (second[0], second[1]),
                    min_offers_per_cycle=1,
                )


class EdekaShadowReplayPersistenceTest(unittest.TestCase):
    def test_full_batches_write_once_and_same_snapshot_replays_write_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = _two_cycles(Path(temporary))
            first_context = _context(SNAPSHOT_ONE, COLLECTED_ONE)
            second_context = _context(SNAPSHOT_TWO, COLLECTED_TWO)
            first_offers = parse_edeka_store_offers_snapshot(
                first[0],
                first[1],
                first_context,
            )
            second_offers = parse_edeka_store_offers_snapshot(
                second[0],
                second[1],
                second_context,
            )

            engine = create_engine("sqlite+pysqlite:///:memory:")
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                for snapshot_id, collected_at, manifest in (
                    (SNAPSHOT_ONE, COLLECTED_ONE, first),
                    (SNAPSHOT_TWO, COLLECTED_TWO, second),
                ):
                    db.add(
                        SourceSnapshot(
                            id=snapshot_id,
                            source_chain="edeka",
                            source_url=SOURCE_URL,
                            final_url=SOURCE_URL,
                            scope="family_primary_edeka",
                            collected_at=collected_at,
                            http_status=200,
                            elapsed_ms=1,
                            content_type=MANIFEST_CONTENT_TYPE,
                            content_bytes=len(manifest[3]),
                            sha256=manifest[1],
                            snapshot_path=str(manifest[0]),
                            keyword_hits={"offer_count": len(manifest[2])},
                            json_ld_blocks=0,
                            strategy_hint=MANIFEST_STRATEGY,
                            success=True,
                            error=None,
                        )
                    )
                db.commit()

                self.assertEqual(
                    save_offer_candidates(db, first_offers),
                    len(first_offers),
                )
                self.assertEqual(save_offer_candidates(db, first_offers), 0)
                self.assertEqual(
                    save_offer_candidates(db, second_offers),
                    len(second_offers),
                )
                self.assertEqual(save_offer_candidates(db, second_offers), 0)

                count = db.scalar(select(func.count(OfferCandidateRecord.id)))
                self.assertEqual(count, len(first_offers) + len(second_offers))

    def test_shadow_ledger_runtime_has_no_database_write_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "app" / "edeka_shadow_ledger.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("SessionLocal", source)
        self.assertNotIn("save_offer_candidates", source)
        self.assertNotIn("sqlalchemy", source)
        self.assertNotIn("db.commit", source)


if __name__ == "__main__":
    unittest.main()
