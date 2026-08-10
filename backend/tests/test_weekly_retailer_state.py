from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from app.weekly_retailer_state import (
    RetailerEvidence,
    _netto_evidence,
    build_weekly_retailer_states,
)
from app.weekly_special_api import (
    WeeklyDayOut,
    WeeklyRetailerStateOut,
    WeeklySpecialsOut,
    _normalize_ui_payload,
)


NOW = datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc)
WEEK_START = date(2026, 8, 10)
WEEK_END = date(2026, 8, 16)


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        snapshot_path="/evidence/netto/manifest.json",
        sha256="a" * 64,
        source_url="https://www.netto-online.de/",
        final_url="https://www.netto-online.de/",
        collected_at=NOW,
    )


def _raw_offer(valid_on: date) -> SimpleNamespace:
    return SimpleNamespace(
        valid_from=valid_on,
        valid_until=valid_on,
        raw_payload={
            "is_daily_special": True,
            "special_confidence": "high",
        },
    )


class NettoRetailerEvidenceTest(unittest.TestCase):
    def test_future_week_without_snapshot_is_not_published_yet(self) -> None:
        with patch("app.weekly_retailer_state._snapshot_query", return_value=[]):
            evidence = _netto_evidence(
                object(),
                date(2026, 8, 17),
                date(2026, 8, 23),
                date(2026, 8, 10),
            )
        self.assertEqual(evidence.state, "not_published_yet")
        self.assertEqual(evidence.reason, "netto_no_successful_snapshot")

    def test_old_verified_window_is_stale_not_empty(self) -> None:
        snapshot = _snapshot()
        with (
            patch("app.weekly_retailer_state._snapshot_query", return_value=[snapshot]),
            patch(
                "app.weekly_retailer_state._snapshot_manifest_window",
                return_value=(date(2026, 8, 3), date(2026, 8, 8)),
            ),
            patch("app.weekly_retailer_state._netto_campaign", return_value="hz32"),
        ):
            evidence = _netto_evidence(
                object(), WEEK_START, WEEK_END, date(2026, 8, 10)
            )
        self.assertEqual(evidence.state, "stale_data")
        self.assertEqual(evidence.last_verified_campaign, "hz32")
        self.assertEqual(evidence.last_verified_valid_until, date(2026, 8, 8))

    def test_relevant_verified_snapshot_with_zero_specials_is_no_offers(self) -> None:
        snapshot = _snapshot()
        with (
            patch("app.weekly_retailer_state._snapshot_query", return_value=[snapshot]),
            patch(
                "app.weekly_retailer_state._snapshot_manifest_window",
                return_value=(date(2026, 8, 10), date(2026, 8, 15)),
            ),
            patch("app.weekly_retailer_state._cached_snapshot_offers", return_value=()),
            patch("app.weekly_retailer_state._netto_campaign", return_value="hz33"),
        ):
            evidence = _netto_evidence(
                object(), WEEK_START, WEEK_END, date(2026, 8, 10)
            )
        self.assertEqual(evidence.state, "no_offers")
        self.assertEqual(evidence.last_verified_campaign, "hz33")

    def test_relevant_parser_failure_is_source_unavailable(self) -> None:
        snapshot = _snapshot()
        with (
            patch("app.weekly_retailer_state._snapshot_query", return_value=[snapshot]),
            patch(
                "app.weekly_retailer_state._snapshot_manifest_window",
                return_value=(date(2026, 8, 10), date(2026, 8, 15)),
            ),
            patch(
                "app.weekly_retailer_state._cached_snapshot_offers",
                side_effect=RuntimeError("bad pdf"),
            ),
        ):
            evidence = _netto_evidence(
                object(), WEEK_START, WEEK_END, date(2026, 8, 10)
            )
        self.assertEqual(evidence.state, "source_unavailable")
        self.assertEqual(evidence.reason, "netto_relevant_snapshot_parse_unavailable")

    def test_verified_special_missing_from_merged_days_fails_closed(self) -> None:
        snapshot = _snapshot()
        with (
            patch("app.weekly_retailer_state._snapshot_query", return_value=[snapshot]),
            patch(
                "app.weekly_retailer_state._snapshot_manifest_window",
                return_value=(date(2026, 8, 10), date(2026, 8, 15)),
            ),
            patch(
                "app.weekly_retailer_state._cached_snapshot_offers",
                return_value=(_raw_offer(date(2026, 8, 10)),),
            ),
        ):
            evidence = _netto_evidence(
                object(), WEEK_START, WEEK_END, date(2026, 8, 10)
            )
        self.assertEqual(evidence.state, "source_unavailable")
        self.assertEqual(
            evidence.reason,
            "netto_verified_offers_missing_from_merged_weekly_days",
        )


class WeeklyRetailerStateContractTest(unittest.TestCase):
    def test_counts_and_active_dates_come_only_from_merged_days(self) -> None:
        deal = SimpleNamespace(
            source_chain="lidl",
            collected_at=NOW,
            valid_from=date(2026, 8, 13),
            valid_until=date(2026, 8, 14),
            source_snapshot_sha256=None,
        )
        days = [
            SimpleNamespace(date=date(2026, 8, 10), deals=[]),
            SimpleNamespace(date=date(2026, 8, 11), deals=[]),
            SimpleNamespace(date=date(2026, 8, 12), deals=[]),
            SimpleNamespace(date=date(2026, 8, 13), deals=[deal]),
            SimpleNamespace(date=date(2026, 8, 14), deals=[deal]),
            SimpleNamespace(date=date(2026, 8, 15), deals=[]),
            SimpleNamespace(date=date(2026, 8, 16), deals=[]),
        ]
        blocked = RetailerEvidence(
            state="source_unavailable",
            reason="fixture_source_unavailable",
        )
        with (
            patch("app.weekly_retailer_state._netto_evidence", return_value=blocked),
            patch("app.weekly_retailer_state._aldi_evidence", return_value=blocked),
        ):
            states = build_weekly_retailer_states(
                object(), days, WEEK_START, WEEK_END, today=date(2026, 8, 10)
            )

        by_key = {row["retailer_key"]: row for row in states}
        self.assertEqual(by_key["lidl"]["state"], "offers")
        self.assertEqual(by_key["lidl"]["deal_count"], 2)
        self.assertEqual(
            by_key["lidl"]["active_dates"],
            [date(2026, 8, 13), date(2026, 8, 14)],
        )
        self.assertEqual(by_key["edeka"]["state"], "not_supported")
        self.assertEqual(by_key["edeka"]["deal_count"], 0)
        self.assertNotEqual(by_key["edeka"]["state"], "no_offers")

    def test_normalized_ui_payload_preserves_retailer_metadata(self) -> None:
        days = [
            WeeklyDayOut(date=WEEK_START.replace(day=10 + offset), deals=[])
            for offset in range(7)
        ]
        retailer = WeeklyRetailerStateOut(
            retailer_key="edeka",
            display_name="EDEKA",
            source_chain="edeka",
            state="not_supported",
            reason="edeka_dedicated_special_period_evidence_not_verified",
            deal_count=0,
            active_dates=[],
        )
        payload = WeeklySpecialsOut(
            week_start=WEEK_START,
            week_end=WEEK_END,
            timezone="Europe/Berlin",
            count=0,
            source_contract=(
                "single_week_query_short_periods_plus_explicit_immutable_daily_evidence"
            ),
            retailers=[retailer],
            days=days,
        )

        normalized = _normalize_ui_payload(payload)

        self.assertEqual(normalized.retailers, [retailer])
        body = normalized.model_dump(mode="json", exclude_none=True)
        self.assertEqual(body["retailers"][0]["state"], "not_supported")
        self.assertEqual(body["retailers"][0]["deal_count"], 0)


if __name__ == "__main__":
    unittest.main()
