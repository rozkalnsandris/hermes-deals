from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.edeka_stale_monitor import evaluate_edeka_health, write_status
from app.edeka_store_offers import MANIFEST_CONTENT_TYPE, MANIFEST_STRATEGY
from app.source_config import SourceConfig


SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"


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


def _success_snapshot(
    root: Path,
    *,
    collected_at: datetime,
    valid_from: str = "2026-08-03",
    valid_until: str = "2026-08-08",
    tamper_raw: bool = False,
):
    snapshot_id = uuid4()
    raw = b"<html><body>EDEKA Patzer verified source</body></html>"
    raw_path = root / "071897-source.html"
    raw_path.write_bytes(raw)
    manifest = {
        "schema_version": 1,
        "strategy": MANIFEST_STRATEGY,
        "snapshot_id": str(snapshot_id),
        "source_chain": "edeka",
        "scope": "family_primary_edeka",
        "public_market_id": "071897",
        "internal_market_id": "587881",
        "store_name": "EDEKA Patzer",
        "source_url": SOURCE_URL,
        "final_url": SOURCE_URL,
        "collected_at": collected_at.isoformat(),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "offer_count": 180,
        "raw_html_path": str(raw_path),
        "raw_html_sha256": sha256(raw).hexdigest(),
        "raw_content_type": "text/html; charset=utf-8",
        "raw_content_bytes": len(raw),
    }
    data = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest_path = root / "manifest.json"
    manifest_path.write_bytes(data)
    if tamper_raw:
        raw_path.write_bytes(raw + b"tampered")
    return SimpleNamespace(
        id=snapshot_id,
        source_chain="edeka",
        source_url=SOURCE_URL,
        final_url=SOURCE_URL,
        scope="family_primary_edeka",
        collected_at=collected_at,
        content_type=MANIFEST_CONTENT_TYPE,
        content_bytes=len(raw),
        sha256=sha256(data).hexdigest(),
        snapshot_path=str(manifest_path),
        strategy_hint=MANIFEST_STRATEGY,
        success=True,
        error=None,
    )


def _failed_attempt(collected_at: datetime, *, success: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        collected_at=collected_at,
        strategy_hint=("generic_probe" if success else f"{MANIFEST_STRATEGY}_error"),
        success=success,
        error=None if success else "upstream unavailable",
    )


class EdekaStaleMonitorTest(unittest.TestCase):
    def _evaluate(self, success, *, now, attempt=None, **kwargs):
        with (
            patch(
                "app.edeka_stale_monitor._latest_success_manifest",
                return_value=success,
            ),
            patch(
                "app.edeka_stale_monitor._latest_attempt",
                return_value=attempt or success,
            ),
        ):
            return evaluate_edeka_health(
                object(),
                _source(),
                now=now,
                **kwargs,
            )

    def test_current_verified_manifest_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=datetime(2026, 8, 5, 10, tzinfo=timezone.utc),
            )
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.offer_count, 180)

    def test_sunday_after_saturday_campaign_end_is_expected_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=datetime(2026, 8, 9, 8, tzinfo=timezone.utc),
            )
        self.assertEqual(result.status, "healthy")
        self.assertFalse(result.critical)

    def test_old_success_is_critical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
                max_success_age_hours=192,
            )
        self.assertTrue(result.critical)
        self.assertIn("successful_manifest_too_old", result.reason)
        self.assertEqual(result.exit_code, 2)

    def test_recent_failed_attempt_stays_in_retry_grace(self) -> None:
        now = datetime(2026, 8, 5, 10, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=now,
                attempt=_failed_attempt(now - timedelta(hours=2)),
                failure_grace_hours=30,
            )
        self.assertEqual(result.status, "warning")
        self.assertFalse(result.critical)
        self.assertEqual(result.exit_code, 0)

    def test_failed_attempt_beyond_retry_grace_is_critical(self) -> None:
        now = datetime(2026, 8, 5, 10, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=now,
                attempt=_failed_attempt(now - timedelta(hours=31)),
                failure_grace_hours=30,
            )
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.critical)

    def test_newer_successful_non_manifest_snapshot_is_rejected(self) -> None:
        now = datetime(2026, 8, 5, 10, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=now,
                attempt=_failed_attempt(now - timedelta(hours=1), success=True),
            )
        self.assertTrue(result.critical)
        self.assertEqual(
            result.reason,
            "newer_non_manifest_snapshot_is_not_authoritative",
        )

    def test_tampered_raw_html_is_critical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            success = _success_snapshot(
                Path(temporary),
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
                tamper_raw=True,
            )
            result = self._evaluate(
                success,
                now=datetime(2026, 8, 5, 10, tzinfo=timezone.utc),
            )
        self.assertTrue(result.critical)
        self.assertIn("raw HTML SHA mismatch", result.reason)

    def test_status_writer_replaces_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            success = _success_snapshot(
                root,
                collected_at=datetime(2026, 8, 3, 5, tzinfo=timezone.utc),
            )
            result = self._evaluate(
                success,
                now=datetime(2026, 8, 5, 10, tzinfo=timezone.utc),
            )
            target = root / "state" / "health.json"
            write_status(target, result)
            payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["exit_code"], 0)


class EdekaSystemdScheduleContractTest(unittest.TestCase):
    def test_timers_are_armed_but_not_activated_by_repository_code(self) -> None:
        root = Path(__file__).resolve().parents[2]
        collector = (
            root / "infra/systemd/hermes-deals-edeka-collector.timer"
        ).read_text(encoding="utf-8")
        monitor = (
            root / "infra/systemd/hermes-deals-edeka-monitor.timer"
        ).read_text(encoding="utf-8")
        service = (
            root / "infra/systemd/hermes-deals-edeka-monitor.service"
        ).read_text(encoding="utf-8")

        self.assertIn("OnCalendar=Mon *-*-* 05:15:00", collector)
        self.assertIn("OnCalendar=Tue *-*-* 05:15:00", collector)
        self.assertIn("Persistent=true", collector)
        for day in ("Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            self.assertIn(f"OnCalendar={day} *-*-* 08:00:00", monitor)
        self.assertIn("python -m app.edeka_stale_monitor", service)
        self.assertIn("--max-success-age-hours 192", service)
        self.assertIn("--failure-grace-hours 30", service)
        for text in (collector, monitor, service):
            self.assertIn("edeka-scheduler-armed", text)
            self.assertNotIn("systemctl enable", text)
            self.assertNotIn("systemctl start", text)

    def test_monitor_has_no_offer_or_database_write_path(self) -> None:
        root = Path(__file__).resolve().parents[2]
        module = (root / "backend/app/edeka_stale_monitor.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("save_offer_candidates", module)
        self.assertNotIn("db.add(", module)
        self.assertNotIn("db.commit(", module)


if __name__ == "__main__":
    unittest.main()
