from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import unittest
from uuid import UUID

from bs4 import BeautifulSoup

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


FIXTURES = Path(__file__).parent / "fixtures"


class EdekaWeeklyHeaderValidityTest(unittest.TestCase):
    def setUp(self) -> None:
        # Reduced from the public 071897 page captured 2026-09-28: its weekly
        # header and two original article/dialog pairs, without legacy starts.
        self.html = (FIXTURES / "edeka_weekly_header_offers.html").read_text()
        self.context = EdekaParserContext(
            snapshot_id=UUID("11111111-2222-4333-8444-555555555555"),
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=datetime(2026, 9, 28, 13, 30, tzinfo=timezone.utc),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def test_parses_current_header_and_replays_identically(self) -> None:
        self.assertNotIn("Gültig ab", self.html)
        offers = parse_edeka_html(self.html, self.context)
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers, parse_edeka_html(self.html, self.context))
        for offer in offers:
            self.assertEqual(str(offer.valid_from), "2026-09-28")
            self.assertEqual(str(offer.valid_until), "2026-10-03")
            self.assertEqual(offer.snapshot_id, self.context.snapshot_id)
            self.assertEqual(offer.source_store_external_id, "071897")
            self.assertEqual(offer.raw_payload["internal_market_id"], "587881")

    def test_legacy_start_must_agree_with_header(self) -> None:
        for start, accepted in [("28.09.2026", True), ("29.09.2026", False)]:
            with self.subTest(start=start):
                html = self.html.replace("</body>", f"<strong>Gültig ab {start}</strong></body>")
                if accepted:
                    self.assertEqual(len(parse_edeka_html(html, self.context)), 2)
                else:
                    with self.assertRaisesRegex(ValueError, "distinct valid_from date, found 2"):
                        parse_edeka_html(html, self.context)

    def test_header_end_must_agree_with_footer(self) -> None:
        html = self.html.replace("<strong>03.10.2026</strong>", "<strong>02.10.2026</strong>")
        with self.assertRaisesRegex(ValueError, "header and footer validity disagree"):
            parse_edeka_html(html, self.context)

    def test_footer_remains_required(self) -> None:
        html = self.html.replace("Alle Angebote gültig bis", "Angebotshinweis bis")
        with self.assertRaisesRegex(ValueError, "distinct valid_until date, found 0"):
            parse_edeka_html(html, self.context)

    def test_rejects_conflicting_header_ranges(self) -> None:
        soup = BeautifulSoup(self.html, "html.parser")
        block = soup.select_one("filter-results > .autoformat")
        other = BeautifulSoup(str(block).replace("28.09.2026", "29.09.2026"), "html.parser")
        block.insert_after(other)
        with self.assertRaisesRegex(ValueError, "distinct valid_from date, found 2"):
            parse_edeka_html(str(soup), self.context)

    def test_rejects_incomplete_header_range(self) -> None:
        html = self.html.replace("bis zum", "bis auf Weiteres")
        with self.assertRaisesRegex(ValueError, "no complete validity range"):
            parse_edeka_html(html, self.context)

    def test_rejects_other_market_header_or_link(self) -> None:
        for old, new in [
            ("Angebote der Woche bei EDEKA Patzer", "Angebote der Woche bei EDEKA Anders"),
            ('href="/maerkte/071897/"', 'href="/maerkte/999999/"'),
        ]:
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, "configured market"):
                parse_edeka_html(self.html.replace(old, new), self.context)

    def test_unrelated_range_cannot_supply_missing_start(self) -> None:
        html = (FIXTURES / "edeka_offers.html").read_text().replace("Gültig ab", "Aktionswoche")
        html = html.replace("</body>", "<aside><p>Gültig vom 20.07.2026 bis zum 25.07.2026.</p></aside></body>")
        with self.assertRaisesRegex(ValueError, "distinct valid_from date, found 0"):
            parse_edeka_html(html, self.context)

    def test_unrelated_coupon_range_does_not_conflict(self) -> None:
        html = self.html.replace("</body>", "<aside><p>Gültig vom 01.09.2026 bis zum 30.09.2026.</p></aside></body>")
        self.assertEqual(len(parse_edeka_html(html, self.context)), 2)

    def test_header_keeps_window_and_freshness_guards(self) -> None:
        for start, end, error in [
            ("04.10.2026", "03.10.2026", "earlier than valid_from"),
            ("20.09.2026", "03.10.2026", "implausibly long"),
            ("31.09.2026", "03.10.2026", "day is out of range"),
        ]:
            with self.subTest(start=start), self.assertRaisesRegex(ValueError, error):
                parse_edeka_html(self.html.replace("28.09.2026", start).replace("03.10.2026", end), self.context)
        for day in [27, 4]:
            month = 9 if day == 27 else 10
            context = replace(self.context, collected_at=datetime(2026, month, day, 12, tzinfo=timezone.utc))
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, "stale or future"):
                parse_edeka_html(self.html, context)


if __name__ == "__main__":
    unittest.main()
