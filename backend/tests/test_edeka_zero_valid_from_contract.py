from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.edeka_failed_source_evidence import (
    EdekaParserExecutionIdentity,
    PARSER_FAILURE_CONTENT_TYPE,
    PARSER_FAILURE_STRATEGY,
    read_parser_failure_manifest,
)
from app.edeka_store_offers import EdekaFetchedPage, collect_edeka_store_offers
from app.source_config import SourceConfig


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
REGISTERED_COMMIT = "4b8ce625cc1d68b13cc802ac04137fdd8161212e"
PARSER_BLOB_SHA = "d691f350573a857a0f1f8351e2f38782a5ff8ae3"
EXPECTED_ERROR = (
    "ValueError: EDEKA expected exactly one distinct valid_from date, found 0: []"
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


def _zero_valid_from_html() -> bytes:
    current = (
        FIXTURE.read_text(encoding="utf-8")
        .replace("20.07.2026", "03.08.2026")
        .replace("25.07.2026", "08.08.2026")
    )
    # Preserve the source date text while removing the only authoritative
    # `Gültig ab` grammar. The parser must fail closed rather than inventing a
    # campaign start from another date on the page.
    without_valid_from = current.replace("Gültig ab", "Aktionswoche")
    if without_valid_from == current:
        raise AssertionError("fixture no longer contains the EDEKA valid_from grammar")
    return without_valid_from.encode("utf-8")


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


class EdekaZeroValidFromContractTest(unittest.TestCase):
    def test_zero_valid_from_is_retained_as_non_authoritative_parser_failure(self) -> None:
        fetched = EdekaFetchedPage(
            final_url=SOURCE_URL,
            content=_zero_valid_from_html(),
            content_type="text/html; charset=utf-8",
            http_status=200,
            elapsed_ms=1,
        )
        identity = EdekaParserExecutionIdentity(
            source_registered_commit=REGISTERED_COMMIT,
            source_parser_blob_sha=PARSER_BLOB_SHA,
            python_implementation="cpython",
            python_version="3.11.0",
        )
        db = _RecordingDb()

        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(raw_snapshot_dir=Path(tmp))
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
                    "app.edeka_store_offers.parser_identity_from_environment",
                    return_value=identity,
                ),
                patch(
                    "app.edeka_store_offers.get_settings",
                    return_value=settings,
                ),
            ):
                result = collect_edeka_store_offers(db, _source())

            self.assertFalse(result.unchanged)
            self.assertFalse(result.snapshot.success)
            self.assertEqual(result.snapshot.content_type, PARSER_FAILURE_CONTENT_TYPE)
            self.assertEqual(result.snapshot.strategy_hint, PARSER_FAILURE_STRATEGY)
            self.assertIn(EXPECTED_ERROR, result.snapshot.error)
            self.assertEqual(db.added, [result.snapshot])
            self.assertEqual(db.commits, 1)
            self.assertEqual(db.refreshed, [result.snapshot])

            manifest_path = Path(result.snapshot.snapshot_path)
            manifest = read_parser_failure_manifest(
                manifest_path,
                result.snapshot.sha256,
            )
            self.assertEqual(manifest["outcome"], "parser_failure")
            self.assertIs(manifest["accepted_campaign"], False)
            self.assertEqual(manifest["public_market_id"], "071897")
            self.assertEqual(manifest["internal_market_id"], "587881")
            self.assertEqual(manifest["source_url"], SOURCE_URL)
            self.assertEqual(manifest["final_url"], SOURCE_URL)
            self.assertEqual(manifest["error"], EXPECTED_ERROR)
            self.assertNotIn("valid_from", manifest)

            raw_path = Path(manifest["raw_html_path"])
            self.assertTrue(raw_path.is_file())
            self.assertEqual(raw_path.read_bytes(), fetched.content)


if __name__ == "__main__":
    unittest.main()
