from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.aldi_current_policy import (
    _derive_current_page_week_end,
    apply_aldi_current_page_policy,
)
from app.schemas import OfferCandidate, SourceChain


def offer(
    *,
    offer_id: str,
    valid_from: date,
    valid_until: date,
    raw_marker: str = "source",
) -> OfferCandidate:
    return OfferCandidate(
        source_chain=SourceChain.ALDI_NORD,
        source_offer_id=offer_id,
        product_name_raw=f"Product {offer_id}",
        price_eur=Decimal("1.99"),
        valid_from=valid_from,
        valid_until=valid_until,
        source_url="https://www.aldi-nord.de/angebote.html",
        snapshot_id=uuid4(),
        collected_at=datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
        parser_version="aldi-nord-v1",
        raw_payload={"marker": raw_marker, "validUntilLocalDate": str(valid_until)},
    )


class AldiCurrentPolicyTest(unittest.TestCase):
    def test_derives_near_term_week_end_and_ignores_one_year_outlier(self) -> None:
        rows = [
            offer(offer_id=f"short-{i}", valid_from=date(2026,7,20), valid_until=date(2026,7,25))
            for i in range(12)
        ]
        rows.append(
            offer(
                offer_id="long",
                valid_from=date(2026,7,20),
                valid_until=date(2027,7,25),
            )
        )
        end, support = _derive_current_page_week_end(
            rows,
            collected_at=datetime(2026,7,25,8,0,tzinfo=timezone.utc),
        )
        self.assertEqual(end, date(2026,7,25))
        self.assertEqual(support, 12)

    def test_current_page_clamps_long_validity(self) -> None:
        rows = [
            offer(offer_id=f"short-{i}", valid_from=date(2026,7,20), valid_until=date(2026,7,25))
            for i in range(12)
        ]
        rows.append(
            offer(
                offer_id="long",
                valid_from=date(2026,7,22),
                valid_until=date(2027,7,23),
            )
        )
        normalized, report = apply_aldi_current_page_policy(
            rows,
            source_url="https://www.aldi-nord.de/angebote.html",
            collected_at=datetime(2026,7,25,8,0,tzinfo=timezone.utc),
        )
        self.assertTrue(report.applied)
        self.assertEqual(report.page_week_end, date(2026,7,25))
        self.assertEqual(report.clamped_count, 1)
        long = next(x for x in normalized if x.source_offer_id == "long")
        self.assertEqual(long.valid_until, date(2026,7,25))
        self.assertEqual(long.parser_version, "aldi-nord-v1.1-current")

    def test_current_policy_preserves_raw_source_payload(self) -> None:
        rows = [
            offer(offer_id=f"short-{i}", valid_from=date(2026,7,20), valid_until=date(2026,7,25))
            for i in range(12)
        ]
        original = offer(
            offer_id="long",
            valid_from=date(2026,7,20),
            valid_until=date(2027,7,25),
            raw_marker="immutable",
        )
        rows.append(original)
        normalized, _ = apply_aldi_current_page_policy(
            rows,
            source_url="https://www.aldi-nord.de/angebote.html",
            collected_at=datetime(2026,7,25,8,0,tzinfo=timezone.utc),
        )
        long = next(x for x in normalized if x.source_offer_id == "long")
        self.assertEqual(long.raw_payload, original.raw_payload)
        self.assertEqual(
            long.raw_payload["validUntilLocalDate"],
            "2027-07-25",
        )

    def test_preview_page_is_not_modified(self) -> None:
        rows = [
            offer(
                offer_id="preview",
                valid_from=date(2026,7,27),
                valid_until=date(2026,8,1),
            )
        ]
        normalized, report = apply_aldi_current_page_policy(
            rows,
            source_url="https://www.aldi-nord.de/angebote-vorschau.html",
            collected_at=datetime(2026,7,25,8,0,tzinfo=timezone.utc),
        )
        self.assertFalse(report.applied)
        self.assertEqual(normalized[0].valid_until, date(2026,8,1))
        self.assertEqual(normalized[0].parser_version, "aldi-nord-v1")


if __name__ == "__main__":
    unittest.main()
