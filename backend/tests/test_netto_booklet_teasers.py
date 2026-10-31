from datetime import date
import unittest

from app.netto_booklet_teasers import extract_netto_booklet_teaser_starts as extract


def card(slug, start, *, url=None, additional=""):
    link = url or f"https://wochenprospekt.netto-online.de/{slug}/?storeid=5659"
    return (
        f'<div class="prospekt-teaser-item"><a href="{link}"><img src="/cover.png"></a>'
        f'<div class="prospekt-teaser-item-container">Filial-Angebote {start} Zum Prospekt'
        f'{additional}</div></div>'
    )


class NettoBookletTeaserTest(unittest.TestCase):
    def test_two_separate_teaser_cards(self):
        html = (
            card("hz44_hasb_4", "ab Montag, 26.10.26")
            + card("hz45_hasb", "ab Montag, 02.11.26")
            + "<div>Preissenkung ab Montag, 19.10.26 01.08.2027</div>"
        )
        self.assertEqual(
            extract(html),
            {"hz44_hasb_4": date(2026, 10, 26), "hz45_hasb": date(2026, 11, 2)},
        )

    def test_unlinked_context_is_never_date_evidence(self):
        self.assertEqual(
            extract("<div>ab Montag, 02.11.26</div>" + card("hz45_hasb", "undated")),
            {},
        )

    def test_conflicting_same_slug_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            extract(
                card("hz45_hasb", "ab Montag, 02.11.26")
                + card("hz45_hasb", "ab Montag, 09.11.26")
            )

    def test_multi_viewer_card_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous.*links"):
            extract(card(
                "hz44_hasb_4", "ab Montag, 26.10.26",
                additional='<a href="https://wochenprospekt.netto-online.de/hz45_hasb/?storeid=5659">other</a>',
            ))

    def test_conflicting_dates_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous.*date"):
            extract(card("hz45_hasb", "ab Montag, 02.11.26 ab Montag, 09.11.26"))

    def test_wrong_store_rejected(self):
        with self.assertRaisesRegex(ValueError, "store mismatch"):
            extract(card(
                "hz45_hasb", "ab Montag, 02.11.26",
                url="https://wochenprospekt.netto-online.de/hz45_hasb/?storeid=6071",
            ))

    def test_wrong_day_rejected(self):
        with self.assertRaisesRegex(ValueError, "weekday mismatch"):
            extract(card("hz45_hasb", "ab Dienstag, 02.11.26"))

    def test_escaped_link_and_four_digit_year(self):
        self.assertEqual(
            extract(card(
                "hz45_hasb", "ab Montag, 02.11.2026",
                url="https://wochenprospekt.netto-online.de/hz45_hasb/?storeid=5659&amp;ref=one",
            )),
            {"hz45_hasb": date(2026, 11, 2)},
        )

    def test_untrusted_host_ignored(self):
        self.assertEqual(extract(card(
            "hz45_hasb", "ab Montag, 02.11.26",
            url="https://example.org/hz45_hasb/?storeid=5659",
        )), {})

    def test_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            extract(card("hz45_hasb", "ab Montag, 32.11.26"))
