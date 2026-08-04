from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException

from app.netto_daily_special_api import _cached_snapshot_offers, daily_specials


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _FakeDb:
    def get_bind(self) -> _Bind:
        return _Bind()

    def scalar(self, statement):
        return None


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID("3ab4cf87-c9fe-4457-972b-781f020a51f2"),
        snapshot_path="/data/raw/netto/manifest.json",
        sha256="a" * 64,
        source_url="https://example.invalid/store",
        final_url="https://example.invalid/prospect",
        collected_at=datetime(
            2026,
            8,
            3,
            7,
            12,
            1,
            tzinfo=timezone.utc,
        ),
    )


class NettoDailySpecialNoPdfTest(unittest.TestCase):
    def test_exact_missing_pdf_returns_explicit_empty_result(self) -> None:
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=_snapshot(),
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                side_effect=RuntimeError(
                    "Netto prospect PDF path is missing"
                ),
            ),
        ):
            payload = daily_specials(
                as_of=date(2026, 8, 3),
                db=_FakeDb(),
            )

        self.assertEqual(payload.as_of, date(2026, 8, 3))
        self.assertEqual(payload.available_count, 0)
        self.assertEqual(payload.count, 0)
        self.assertEqual(payload.retailer_counts, {})
        self.assertEqual(payload.deals, [])
        self.assertEqual(
            payload.source_contract,
            "explicit_immutable_retailer_evidence_only",
        )

    def test_other_runtime_evidence_failure_remains_503(self) -> None:
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=_snapshot(),
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                side_effect=RuntimeError(
                    "Netto prospect PDF checksum mismatch"
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                daily_specials(
                    as_of=date(2026, 8, 3),
                    db=_FakeDb(),
                )

        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn(
            "checksum mismatch",
            str(caught.exception.detail),
        )

    def test_invalid_manifest_remains_explicit_503(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text("[]", encoding="utf-8")
            snapshot = _snapshot()
            snapshot.snapshot_path = str(manifest_path)
            snapshot.sha256 = sha256(manifest_path.read_bytes()).hexdigest()
            _cached_snapshot_offers.cache_clear()
            with (
                patch(
                    "app.netto_daily_special_api._latest_snapshot",
                    return_value=snapshot,
                ),
                self.assertRaises(HTTPException) as caught,
            ):
                daily_specials(as_of=date(2026, 8, 3), db=_FakeDb())
            _cached_snapshot_offers.cache_clear()

        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("must be a JSON object", str(caught.exception.detail))


if __name__ == "__main__":
    unittest.main()
