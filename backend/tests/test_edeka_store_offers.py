from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from app.edeka_store_offers import (
    EdekaFetchedPage,
    MANIFEST_CONTENT_TYPE,
    MANIFEST_STRATEGY,
    OFFER_SEMANTIC_FINGERPRINT_VERSION,
    _write_manifest,
    collect_edeka_store_offers,
    parse_edeka_store_offers_snapshot,
)
from app.parsers.edeka import EdekaParserContext, parse_edeka_html
from app.source_config import SourceConfig


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("11111111-2222-4333-8444-555555555555")


def _current_html() -> bytes:
    return (
        FIXTURE.read_text(encoding="utf-8")
        .replace("20.07.2026", "03.08.2026")
        .replace("25.07.2026", "08.08.2026")
        .encode("utf-8")
    )


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


def _context(snapshot_id=SNAPSHOT_ID) -> EdekaParserContext:
    return EdekaParserContext(
        snapshot_id=snapshot_id,
        source_url=SOURCE_URL,
        collected_at=COLLECTED_AT,
        public_market_id="071897",
        internal_market_id="587881",
        store_name="EDEKA Patzer",
    )


def _fetched(content: bytes | None = None) -> EdekaFetchedPage:
    return EdekaFetchedPage(
        final_url=SOURCE_URL,
        content=content if content is not None else _current_html(),
        content_type="text/html; charset=utf-8",
        http_status=200,
        elapsed_ms=1,
    )


class _NoWriteDb:
    def add(self, value) -> None:
        raise AssertionError("unchanged source must not add a SourceSnapshot")

    def commit(self) -> None:
        raise AssertionError("unchanged source must not commit")

    def refresh(self, value) -> None:
        raise AssertionError("unchanged source must not refresh")


class _RecordingDb:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0
        self.refreshed = []

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, value) -> None:
        self.refreshed.append(value)


class EdekaImmutableManifestTest(unittest.TestCase):
    def test_manifest_round_trip_binds_patzer_window_and_raw_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            fetched = _fetched()
            offers = parse_edeka_html(fetched.content, _context())
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=SNAPSHOT_ID,
                    collected_at=COLLECTED_AT,
                    fetched=fetched,
                    offers=offers,
                )
                parsed = parse_edeka_store_offers_snapshot(
                    manifest_path,
                    manifest_sha,
                    _context(),
                )

            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            raw_path = Path(manifest["raw_html_path"])

            self.assertEqual(manifest["strategy"], MANIFEST_STRATEGY)
            self.assertEqual(manifest["public_market_id"], "071897")
            self.assertEqual(manifest["internal_market_id"], "587881")
            self.assertEqual(manifest["valid_from"], "2026-08-03")
            self.assertEqual(manifest["valid_until"], "2026-08-08")
            self.assertEqual(manifest["offer_count"], len(parsed))
            self.assertEqual(
                manifest["offer_semantic_fingerprint_version"],
                OFFER_SEMANTIC_FINGERPRINT_VERSION,
            )
            self.assertEqual(len(manifest["offer_semantic_sha256"]), 64)
            self.assertTrue(raw_path.name.startswith("071897-offers-"))
            self.assertEqual(len(parsed), 2)

    def test_tampered_raw_html_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            fetched = _fetched()
            offers = parse_edeka_html(fetched.content, _context())
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=SNAPSHOT_ID,
                    collected_at=COLLECTED_AT,
                    fetched=fetched,
                    offers=offers,
                )

            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            raw_path = Path(manifest["raw_html_path"])
            raw_path.write_bytes(raw_path.read_bytes() + b"tampered")

            with self.assertRaisesRegex(
                ValueError,
                "raw HTML SHA mismatch",
            ):
                parse_edeka_store_offers_snapshot(
                    manifest_path,
                    manifest_sha,
                    _context(),
                )

    def test_wrong_market_context_fails_before_offer_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            fetched = _fetched()
            offers = parse_edeka_html(fetched.content, _context())
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=SNAPSHOT_ID,
                    collected_at=COLLECTED_AT,
                    fetched=fetched,
                    offers=offers,
                )

            wrong = EdekaParserContext(
                snapshot_id=SNAPSHOT_ID,
                source_url=SOURCE_URL,
                collected_at=COLLECTED_AT,
                public_market_id="999999",
                internal_market_id="587881",
                store_name="EDEKA Patzer",
            )
            with self.assertRaisesRegex(
                ValueError,
                "public_market_id mismatch",
            ):
                parse_edeka_store_offers_snapshot(
                    manifest_path,
                    manifest_sha,
                    wrong,
                )

    def test_identical_current_source_is_complete_database_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            previous_id = uuid4()
            fetched = _fetched()
            previous_context = _context(previous_id)
            previous_offers = parse_edeka_html(
                fetched.content,
                previous_context,
            )
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=previous_id,
                    collected_at=COLLECTED_AT,
                    fetched=fetched,
                    offers=previous_offers,
                )
                previous = SimpleNamespace(
                    id=previous_id,
                    source_chain="edeka",
                    source_url=SOURCE_URL,
                    final_url=SOURCE_URL,
                    scope="family_primary_edeka",
                    collected_at=COLLECTED_AT,
                    content_type=MANIFEST_CONTENT_TYPE,
                    snapshot_path=str(manifest_path),
                    sha256=manifest_sha,
                    success=True,
                    error=None,
                    http_status=200,
                )
                with (
                    patch(
                        "app.edeka_store_offers._utc_now",
                        return_value=COLLECTED_AT,
                    ),
                    patch(
                        "app.edeka_store_offers.fetch_edeka_store_offers",
                        return_value=fetched,
                    ),
                    patch(
                        "app.edeka_store_offers._latest_manifest_snapshot",
                        return_value=previous,
                    ),
                ):
                    result = collect_edeka_store_offers(
                        _NoWriteDb(),
                        _source(),
                    )

            self.assertTrue(result.unchanged)
            self.assertIs(result.snapshot, previous)

    def test_volatile_html_with_identical_offers_is_database_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            previous_id = uuid4()
            previous_fetched = _fetched()
            previous_offers = parse_edeka_html(
                previous_fetched.content,
                _context(previous_id),
            )
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=previous_id,
                    collected_at=COLLECTED_AT,
                    fetched=previous_fetched,
                    offers=previous_offers,
                )
                previous = SimpleNamespace(
                    id=previous_id,
                    source_chain="edeka",
                    source_url=SOURCE_URL,
                    final_url=SOURCE_URL,
                    scope="family_primary_edeka",
                    collected_at=COLLECTED_AT,
                    content_type=MANIFEST_CONTENT_TYPE,
                    snapshot_path=str(manifest_path),
                    sha256=manifest_sha,
                    success=True,
                    error=None,
                    http_status=200,
                )
                volatile = _fetched(
                    previous_fetched.content
                    + b"\n<!-- volatile-request-id=abcdef -->\n"
                )
                self.assertNotEqual(
                    sha256(previous_fetched.content).hexdigest(),
                    sha256(volatile.content).hexdigest(),
                )
                with (
                    patch(
                        "app.edeka_store_offers._utc_now",
                        return_value=COLLECTED_AT,
                    ),
                    patch(
                        "app.edeka_store_offers.fetch_edeka_store_offers",
                        return_value=volatile,
                    ),
                    patch(
                        "app.edeka_store_offers._latest_manifest_snapshot",
                        return_value=previous,
                    ),
                ):
                    result = collect_edeka_store_offers(
                        _NoWriteDb(),
                        _source(),
                    )

            self.assertTrue(result.unchanged)
            self.assertIs(result.snapshot, previous)

    def test_semantic_offer_change_is_not_database_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            previous_id = uuid4()
            previous_fetched = _fetched()
            previous_offers = parse_edeka_html(
                previous_fetched.content,
                _context(previous_id),
            )
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=previous_id,
                    collected_at=COLLECTED_AT,
                    fetched=previous_fetched,
                    offers=previous_offers,
                )
                previous = SimpleNamespace(
                    id=previous_id,
                    source_chain="edeka",
                    source_url=SOURCE_URL,
                    final_url=SOURCE_URL,
                    scope="family_primary_edeka",
                    collected_at=COLLECTED_AT,
                    content_type=MANIFEST_CONTENT_TYPE,
                    snapshot_path=str(manifest_path),
                    sha256=manifest_sha,
                    success=True,
                    error=None,
                    http_status=200,
                )
                changed = _fetched(
                    previous_fetched.content.replace(
                        b"Festpreis von 1.11",
                        b"Festpreis von 1.12",
                        1,
                    )
                )
                db = _RecordingDb()
                with (
                    patch(
                        "app.edeka_store_offers._utc_now",
                        return_value=COLLECTED_AT,
                    ),
                    patch(
                        "app.edeka_store_offers.fetch_edeka_store_offers",
                        return_value=changed,
                    ),
                    patch(
                        "app.edeka_store_offers._latest_manifest_snapshot",
                        return_value=previous,
                    ),
                ):
                    result = collect_edeka_store_offers(db, _source())

            self.assertFalse(result.unchanged)
            self.assertTrue(result.snapshot.success)
            self.assertEqual(db.added, [result.snapshot])
            self.assertEqual(db.commits, 1)
            self.assertEqual(db.refreshed, [result.snapshot])

    def test_legacy_manifest_without_semantic_fingerprint_still_noops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
            previous_id = uuid4()
            fetched = _fetched()
            previous_offers = parse_edeka_html(
                fetched.content,
                _context(previous_id),
            )
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, _ = _write_manifest(
                    source=_source(),
                    snapshot_id=previous_id,
                    collected_at=COLLECTED_AT,
                    fetched=fetched,
                    offers=previous_offers,
                )
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                manifest.pop("offer_semantic_fingerprint_version")
                manifest.pop("offer_semantic_sha256")
                legacy_data = json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                legacy_path = Path(tmp) / "legacy-manifest.json"
                legacy_path.write_bytes(legacy_data)
                legacy_sha = sha256(legacy_data).hexdigest()
                previous = SimpleNamespace(
                    id=previous_id,
                    source_chain="edeka",
                    source_url=SOURCE_URL,
                    final_url=SOURCE_URL,
                    scope="family_primary_edeka",
                    collected_at=COLLECTED_AT,
                    content_type=MANIFEST_CONTENT_TYPE,
                    snapshot_path=str(legacy_path),
                    sha256=legacy_sha,
                    success=True,
                    error=None,
                    http_status=200,
                )
                volatile = _fetched(
                    fetched.content + b"\n<!-- volatile-request-id=legacy -->\n"
                )
                with (
                    patch(
                        "app.edeka_store_offers._utc_now",
                        return_value=COLLECTED_AT,
                    ),
                    patch(
                        "app.edeka_store_offers.fetch_edeka_store_offers",
                        return_value=volatile,
                    ),
                    patch(
                        "app.edeka_store_offers._latest_manifest_snapshot",
                        return_value=previous,
                    ),
                ):
                    result = collect_edeka_store_offers(
                        _NoWriteDb(),
                        _source(),
                    )

            self.assertTrue(result.unchanged)
            self.assertIs(result.snapshot, previous)

    def test_stale_source_records_failure_without_offer_authority(self) -> None:
        db = _RecordingDb()
        stale = _fetched(FIXTURE.read_bytes())
        with (
            patch(
                "app.edeka_store_offers._utc_now",
                return_value=COLLECTED_AT,
            ),
            patch(
                "app.edeka_store_offers.fetch_edeka_store_offers",
                return_value=stale,
            ),
        ):
            result = collect_edeka_store_offers(db, _source())

        self.assertFalse(result.unchanged)
        self.assertFalse(result.snapshot.success)
        self.assertIn("stale or future catalogue", result.snapshot.error)
        self.assertEqual(db.added, [result.snapshot])
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.refreshed, [result.snapshot])


if __name__ == "__main__":
    unittest.main()
