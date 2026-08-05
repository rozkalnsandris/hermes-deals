from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.edeka_shadow_capture import capture_edeka_shadow_cycle
from app.edeka_store_offers import EdekaFetchedPage


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


def _current_html() -> bytes:
    return (
        FIXTURE.read_text(encoding="utf-8")
        .replace("20.07.2026", "03.08.2026")
        .replace("25.07.2026", "08.08.2026")
        .encode("utf-8")
    )


def _write_sources(path: Path, *, public_id: str = "071897") -> Path:
    payload = {
        "schema_version": 1,
        "sources": [
            {
                "chain": "edeka",
                "enabled": True,
                "priority": 2,
                "url": SOURCE_URL,
                "scope": "family_primary_edeka",
                "notes": "test",
                "keywords": ["Angebote"],
                "store_external_id": public_id,
                "store_internal_id": "587881",
                "store_name": "EDEKA Patzer",
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fetched() -> EdekaFetchedPage:
    content = _current_html()
    return EdekaFetchedPage(
        final_url=SOURCE_URL,
        content=content,
        content_type="text/html; charset=utf-8",
        http_status=200,
        elapsed_ms=4,
    )


def _table_count(database: Path, table: str) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


class EdekaShadowCaptureTest(unittest.TestCase):
    def _capture(self, root: Path, *, min_offers: int = 1):
        sources = _write_sources(root / "sources.json")
        output = root / "cycle"
        with (
            patch(
                "app.edeka_store_offers.fetch_edeka_store_offers",
                return_value=_fetched(),
            ),
            patch(
                "app.edeka_store_offers._utc_now",
                return_value=COLLECTED_AT,
            ),
        ):
            result = capture_edeka_shadow_cycle(
                output,
                sources,
                min_offers=min_offers,
            )
        return output, result

    def test_capture_uses_isolated_sqlite_and_replay_writes_zero(self) -> None:
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://production-forbidden/example"
        try:
            with tempfile.TemporaryDirectory() as temporary:
                output, result = self._capture(Path(temporary))

                evidence = json.loads(
                    (output / "cycle-evidence.json").read_text(encoding="utf-8")
                )
                database = output / "shadow.sqlite3"
                manifest_rel = evidence["files"]["manifest"]["path"]
                raw_rel = evidence["files"]["raw_html"]["path"]

                self.assertEqual(result["result"], "pass")
                self.assertGreater(result["offer_count"], 0)
                self.assertEqual(
                    result["first_write_offer_delta"],
                    result["offer_count"],
                )
                self.assertEqual(result["same_snapshot_replay_offer_delta"], 0)
                self.assertEqual(
                    evidence["isolated_persistence"]["database_engine"],
                    "sqlite",
                )
                self.assertFalse(
                    evidence["isolated_persistence"][
                        "production_database_write"
                    ]
                )
                self.assertFalse(evidence["safety"]["production_deployment"])
                self.assertFalse(evidence["safety"]["review_write"])
                self.assertFalse(evidence["safety"]["publication_write"])
                self.assertEqual(_table_count(database, "source_snapshots"), 1)
                self.assertEqual(
                    _table_count(database, "offer_candidates"),
                    result["offer_count"],
                )
                self.assertTrue((output / manifest_rel).is_file())
                self.assertTrue((output / raw_rel).is_file())
                self.assertTrue((output / "normalization-report.json").is_file())
        finally:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url

        self.assertEqual(
            os.environ.get("DATABASE_URL"),
            previous_database_url,
        )

    def test_sha256s_bind_every_evidence_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self._capture(Path(temporary))
            lines = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()

            self.assertGreaterEqual(len(lines), 5)
            listed: set[str] = set()
            for line in lines:
                digest, relative = line.split("  ", 1)
                path = output / relative
                self.assertTrue(path.is_file())
                self.assertEqual(sha256(path.read_bytes()).hexdigest(), digest)
                listed.add(relative)

            self.assertIn("cycle-evidence.json", listed)
            self.assertIn("normalization-report.json", listed)
            self.assertIn("shadow.sqlite3", listed)

    def test_minimum_gate_leaves_source_evidence_but_no_offer_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = _write_sources(root / "sources.json")
            output = root / "cycle"
            with (
                patch(
                    "app.edeka_store_offers.fetch_edeka_store_offers",
                    return_value=_fetched(),
                ),
                patch(
                    "app.edeka_store_offers._utc_now",
                    return_value=COLLECTED_AT,
                ),
            ):
                with self.assertRaisesRegex(ValueError, "below the production-scale"):
                    capture_edeka_shadow_cycle(
                        output,
                        sources,
                        min_offers=999,
                    )

            database = output / "shadow.sqlite3"
            self.assertTrue(database.is_file())
            self.assertEqual(_table_count(database, "source_snapshots"), 1)
            self.assertEqual(_table_count(database, "offer_candidates"), 0)
            self.assertFalse((output / "cycle-evidence.json").exists())

    def test_nonempty_output_fails_before_network_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = _write_sources(root / "sources.json")
            output = root / "cycle"
            output.mkdir()
            (output / "unexpected.txt").write_text("occupied", encoding="utf-8")

            with patch(
                "app.edeka_store_offers.fetch_edeka_store_offers"
            ) as fetch:
                with self.assertRaisesRegex(ValueError, "must be empty"):
                    capture_edeka_shadow_cycle(output, sources, min_offers=1)
            fetch.assert_not_called()

    def test_wrong_market_config_fails_before_network_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = _write_sources(root / "sources.json", public_id="999999")
            with patch(
                "app.edeka_store_offers.fetch_edeka_store_offers"
            ) as fetch:
                with self.assertRaisesRegex(ValueError, "public market ID mismatch"):
                    capture_edeka_shadow_cycle(
                        root / "cycle",
                        sources,
                        min_offers=1,
                    )
            fetch.assert_not_called()

    def test_runtime_module_has_no_production_session_or_deploy_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "app" / "edeka_shadow_capture.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("SessionLocal", source)
        self.assertNotIn("docker", source.lower())
        self.assertNotIn("systemctl", source.lower())
        self.assertNotIn("postgresql", source.lower())
        self.assertIn("create_engine(database_url)", source)
        self.assertIn('"production_database_write": False', source)


if __name__ == "__main__":
    unittest.main()
