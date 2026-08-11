from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

from app.edeka_failed_source_evidence import (
    PARSER_CONTRACT_VERSION,
    PARSER_FAILURE_CONTENT_TYPE,
    PARSER_FAILURE_STRATEGY,
    cleanup_failure_evidence,
    read_parser_failure_manifest,
    replay_parser_failure_offline,
    retain_raw_source,
)
from app.edeka_store_offers import (
    EdekaFetchedPage,
    collect_edeka_store_offers,
    parse_edeka_store_offers_snapshot,
)
from app.parsers.edeka import EdekaParserContext
from app.source_config import SourceConfig


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
REGISTERED_COMMIT = "1" * 40
PARSER_BLOB = "a" * 40


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


def _stale_fetched(*, raw_evidence=None) -> EdekaFetchedPage:
    return EdekaFetchedPage(
        final_url=SOURCE_URL,
        content=FIXTURE.read_bytes(),
        content_type="text/html; charset=utf-8",
        http_status=200,
        elapsed_ms=7,
        raw_evidence=raw_evidence,
    )


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


class EdekaFailedSourceEvidenceTest(unittest.TestCase):
    def _capture_failure(self, root: Path):
        db = _RecordingDb()
        settings = SimpleNamespace(raw_snapshot_dir=root)
        environment = {
            "EDEKA_SOURCE_REGISTERED_COMMIT": REGISTERED_COMMIT,
            "EDEKA_SOURCE_PARSER_BLOB_SHA": PARSER_BLOB,
        }
        with (
            patch.dict(os.environ, environment, clear=False),
            patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ),
            patch(
                "app.edeka_store_offers._utc_now",
                return_value=COLLECTED_AT,
            ),
            patch(
                "app.edeka_store_offers.fetch_edeka_store_offers",
                return_value=_stale_fetched(),
            ),
        ):
            result = collect_edeka_store_offers(db, _source())
        return result, db

    def test_parser_failure_retains_raw_and_disjoint_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, db = self._capture_failure(root)

            self.assertFalse(result.unchanged)
            self.assertFalse(result.snapshot.success)
            self.assertEqual(result.snapshot.content_type, PARSER_FAILURE_CONTENT_TYPE)
            self.assertEqual(result.snapshot.strategy_hint, PARSER_FAILURE_STRATEGY)
            self.assertEqual(db.added, [result.snapshot])
            self.assertEqual(db.commits, 1)
            self.assertEqual(db.refreshed, [result.snapshot])
            self.assertIsNotNone(result.snapshot.snapshot_path)
            self.assertIsNotNone(result.snapshot.sha256)

            manifest_path = Path(result.snapshot.snapshot_path)
            manifest = read_parser_failure_manifest(
                manifest_path,
                result.snapshot.sha256,
            )
            self.assertEqual(manifest["parser_contract_version"], PARSER_CONTRACT_VERSION)
            self.assertEqual(manifest["source_registered_commit"], REGISTERED_COMMIT)
            self.assertEqual(manifest["source_parser_blob_sha"], PARSER_BLOB)
            self.assertFalse(manifest["accepted_campaign"])
            raw_path = Path(manifest["raw_html_path"])
            self.assertEqual(raw_path.read_bytes(), FIXTURE.read_bytes())
            self.assertEqual(
                manifest["raw_html_sha256"],
                sha256(FIXTURE.read_bytes()).hexdigest(),
            )

    def test_failure_without_registered_identity_keeps_raw_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = retain_raw_source(
                root,
                public_market_id="071897",
                content=FIXTURE.read_bytes(),
            )
            db = _RecordingDb()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "app.edeka_store_offers._utc_now",
                    return_value=COLLECTED_AT,
                ),
                patch(
                    "app.edeka_store_offers.fetch_edeka_store_offers",
                    return_value=_stale_fetched(raw_evidence=raw),
                ),
            ):
                result = collect_edeka_store_offers(db, _source())

            self.assertFalse(result.snapshot.success)
            self.assertEqual(result.snapshot.snapshot_path, str(raw.path))
            self.assertEqual(result.snapshot.sha256, raw.sha256)
            self.assertIn("identity_unavailable", result.snapshot.strategy_hint)
            self.assertEqual(result.snapshot.keyword_hits["parser_identity_bound"], 0)

    def test_failure_manifest_cannot_be_consumed_as_accepted_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self._capture_failure(Path(tmp))
            context = EdekaParserContext(
                snapshot_id=UUID(str(result.snapshot.id)),
                source_url=SOURCE_URL,
                collected_at=COLLECTED_AT,
                public_market_id="071897",
                internal_market_id="587881",
                store_name="EDEKA Patzer",
            )
            with self.assertRaisesRegex(ValueError, "manifest (schema_version|strategy) mismatch"):
                parse_edeka_store_offers_snapshot(
                    Path(result.snapshot.snapshot_path),
                    result.snapshot.sha256,
                    context,
                )

    def test_retained_raw_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = retain_raw_source(
                root,
                public_market_id="071897",
                content=b"original",
            )
            evidence.path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "Refusing to replace immutable"):
                retain_raw_source(
                    root,
                    public_market_id="071897",
                    content=b"original",
                )

    def test_source_identity_drift_fails_before_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _source()
            source = SourceConfig(
                chain=source.chain,
                enabled=source.enabled,
                priority=source.priority,
                url="https://www.edeka.de/maerkte/999999/angebote/",
                scope=source.scope,
                notes=source.notes,
                keywords=source.keywords,
                store_external_id=source.store_external_id,
                store_internal_id=source.store_internal_id,
                store_name=source.store_name,
            )
            db = _RecordingDb()
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=SimpleNamespace(raw_snapshot_dir=root),
            ):
                with self.assertRaisesRegex(ValueError, "source URL is not Patzer"):
                    collect_edeka_store_offers(db, source)
            self.assertFalse((root / "edeka").exists())
            self.assertEqual(db.added, [])

    def test_offline_replay_uses_retained_bytes_and_separate_derivation_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self._capture_failure(Path(tmp))
            with patch(
                "httpx.Client",
                side_effect=AssertionError("offline replay must not refetch EDEKA"),
            ):
                replay = replay_parser_failure_offline(
                    Path(result.snapshot.snapshot_path),
                    result.snapshot.sha256,
                    derivation_registered_commit="2" * 40,
                    derivation_parser_blob_sha=PARSER_BLOB,
                )
            self.assertFalse(replay["network_refetch"])
            self.assertEqual(replay["source_registered_commit"], REGISTERED_COMMIT)
            self.assertEqual(replay["derivation_registered_commit"], "2" * 40)
            self.assertEqual(replay["raw_html_sha256"], sha256(FIXTURE.read_bytes()).hexdigest())

    def test_cleanup_requires_snapshot_inventory_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "complete SourceSnapshot path inventory"):
                cleanup_failure_evidence(root, max_manifests=2, apply=True)

    def test_cleanup_is_bounded_and_preserves_snapshot_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            edeka = root / "edeka"
            edeka.mkdir()
            raw_paths = []
            manifest_paths = []
            for index in range(4):
                raw = edeka / f"071897-offers-{'a' * 63}{index}.html"
                raw.write_bytes(f"raw-{index}".encode())
                raw_paths.append(raw)
                manifest = {"raw_html_path": str(raw.resolve())}
                path = edeka / (
                    f"2026080{index + 1}T090000Z-071897-parser-failure-manifest-"
                    f"{index:012d}.json"
                )
                path.write_text(json.dumps(manifest), encoding="utf-8")
                manifest_paths.append(path)

            plan = cleanup_failure_evidence(root, max_manifests=2)
            self.assertEqual(plan["kept"], 2)
            self.assertEqual(len(plan["expired"]), 2)
            self.assertFalse(plan["applied"])
            self.assertTrue(all(path.exists() for path in raw_paths))

            applied = cleanup_failure_evidence(
                root,
                max_manifests=2,
                source_snapshot_paths={manifest_paths[0]},
                apply=True,
            )
            self.assertTrue(applied["applied"])
            self.assertEqual(
                applied["protected_snapshot_manifests"],
                [str(manifest_paths[0])],
            )
            self.assertTrue(manifest_paths[0].exists())
            self.assertFalse(manifest_paths[1].exists())
            self.assertTrue(manifest_paths[2].exists())
            self.assertTrue(manifest_paths[3].exists())
            self.assertTrue(raw_paths[0].exists())
            self.assertFalse(raw_paths[1].exists())
            self.assertTrue(raw_paths[2].exists())
            self.assertTrue(raw_paths[3].exists())


if __name__ == "__main__":
    unittest.main()
