from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from uuid import uuid4

from fastapi import HTTPException

from app.netto_daily_special_api import (
    _cached_snapshot_offers,
    _latest_snapshot,
    daily_specials,
)


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _ScalarRows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)

    def get_bind(self):
        return _Bind()

    def scalars(self, statement):
        return _ScalarRows(self._snapshots)

    def scalar(self, statement):
        # No ALDI Nord snapshot in these focused Netto tests.
        return None


def _snapshot(
    root: Path,
    *,
    name: str,
    valid_from: date,
    valid_until: date,
    collected_at: datetime,
    sha_override: str | None = None,
):
    manifest = {
        "schema_version": 3,
        "strategy": "netto_store_page_plus_current_prospect_pdf_v3",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "prospect_slug": name,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        # Deliberately omitted PDF evidence models a legacy snapshot. Selection
        # may use its verified campaign window, while the existing endpoint
        # contract still returns an explicit empty result rather than inferring
        # daily offers from ordinary weekly HTML cards.
        "prospect_pdf_path": None,
        "prospect_pdf_sha256": None,
    }
    path = root / f"{name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return SimpleNamespace(
        id=uuid4(),
        snapshot_path=str(path),
        sha256=sha_override or sha256(path.read_bytes()).hexdigest(),
        source_url="https://example.invalid/store",
        final_url=f"https://example.invalid/{name}",
        collected_at=collected_at,
    )


class NettoDailySnapshotSelectionTest(unittest.TestCase):
    def test_older_matching_window_is_selected_over_newer_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            newer = _snapshot(
                root,
                name="next-week",
                valid_from=date(2026, 8, 10),
                valid_until=date(2026, 8, 15),
                collected_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            )
            older = _snapshot(
                root,
                name="requested-week",
                valid_from=date(2026, 8, 3),
                valid_until=date(2026, 8, 8),
                collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )

            selected = _latest_snapshot(
                _FakeDb([newer, older]),
                date(2026, 8, 4),
            )

        self.assertIs(selected, older)

    def test_no_matching_campaign_returns_no_netto_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(
                Path(tmp),
                name="next-week",
                valid_from=date(2026, 8, 10),
                valid_until=date(2026, 8, 15),
                collected_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            )
            selected = _latest_snapshot(
                _FakeDb([snapshot]),
                date(2026, 8, 4),
            )

        self.assertIsNone(selected)

    def test_route_returns_explicit_empty_when_no_campaign_covers_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(
                Path(tmp),
                name="next-week",
                valid_from=date(2026, 8, 10),
                valid_until=date(2026, 8, 15),
                collected_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            )
            payload = daily_specials(
                as_of=date(2026, 8, 4),
                db=_FakeDb([snapshot]),
            )

        self.assertEqual(payload.available_count, 0)
        self.assertEqual(payload.count, 0)
        self.assertEqual(payload.retailer_counts, {})
        self.assertEqual(payload.deals, [])
        self.assertEqual(
            payload.source_contract,
            "explicit_immutable_retailer_evidence_only",
        )

    def test_matching_legacy_snapshot_without_pdf_stays_safe_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(
                Path(tmp),
                name="legacy-current-week",
                valid_from=date(2026, 8, 3),
                valid_until=date(2026, 8, 8),
                collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
            )
            _cached_snapshot_offers.cache_clear()
            payload = daily_specials(
                as_of=date(2026, 8, 4),
                db=_FakeDb([snapshot]),
            )
            _cached_snapshot_offers.cache_clear()

        self.assertEqual(payload.count, 0)
        self.assertEqual(payload.deals, [])

    def test_manifest_sha_mismatch_remains_explicit_503(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = _snapshot(
                Path(tmp),
                name="tampered-week",
                valid_from=date(2026, 8, 3),
                valid_until=date(2026, 8, 8),
                collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
                sha_override="0" * 64,
            )
            with self.assertRaises(HTTPException) as caught:
                _latest_snapshot(
                    _FakeDb([snapshot]),
                    date(2026, 8, 4),
                )

        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("SHA mismatch", str(caught.exception.detail))

    def test_no_snapshots_remains_explicit_503(self):
        with self.assertRaises(HTTPException) as caught:
            _latest_snapshot(_FakeDb([]), date(2026, 8, 4))

        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("snapshots are unavailable", str(caught.exception.detail))


if __name__ == "__main__":
    unittest.main()
