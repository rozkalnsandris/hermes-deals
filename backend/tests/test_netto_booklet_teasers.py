from datetime import date
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from app.netto_booklet_teasers import extract_netto_booklet_teaser_starts as extract
from app.netto_booklets import (
    _TEASER_STARTS_CACHE,
    _TEASER_STARTS_CACHE_LIMIT,
    _verified_html,
    _verified_teaser_starts,
)


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

class NettoVerifiedTeaserCacheTest(unittest.TestCase):
    def setUp(self):
        _TEASER_STARTS_CACHE.clear()

    def tearDown(self):
        _TEASER_STARTS_CACHE.clear()

    def test_verified_source_parsed_once_and_returned_as_fresh_mapping(self):
        raw = card("hz45_hasb", "ab Montag, 02.11.26").encode()
        digest = sha256(raw).hexdigest()
        with patch(
            "app.netto_booklet_teasers.extract_netto_booklet_teaser_starts",
            wraps=extract,
        ) as parser:
            first = _verified_teaser_starts(raw, digest)
            first.clear()
            second = _verified_teaser_starts(raw, digest)
        self.assertEqual(second, {"hz45_hasb": date(2026, 11, 2)})
        self.assertEqual(parser.call_count, 1)

    def test_tampered_bytes_are_rejected_even_with_warm_cache(self):
        raw = card("hz45_hasb", "ab Montag, 02.11.26").encode()
        digest = sha256(raw).hexdigest()
        self.assertIn("hz45_hasb", _verified_teaser_starts(raw, digest))
        with self.assertRaisesRegex(ValueError, "integrity"):
            _verified_teaser_starts(raw + b"tampered", digest)
        self.assertEqual(len(_TEASER_STARTS_CACHE), 1)

    def test_changed_raw_file_fails_before_cache_consultation(self):
        raw = card("hz45_hasb", "ab Montag, 02.11.26").encode()
        digest = sha256(raw).hexdigest()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            evidence_dir = root / "netto-html"
            evidence_dir.mkdir()
            path = evidence_dir / "official.html"
            path.write_bytes(raw)
            self.assertEqual(
                _verified_teaser_starts(_verified_html(str(path), digest, root), digest),
                {"hz45_hasb": date(2026, 11, 2)},
            )
            path.write_bytes(raw + b"corrupted")
            with self.assertRaisesRegex(ValueError, "integrity"):
                _verified_html(str(path), digest, root)

    def test_invalid_parsing_is_not_cached(self):
        raw = card("hz45_hasb", "ab Dienstag, 02.11.26").encode()
        with self.assertRaisesRegex(ValueError, "weekday mismatch"):
            _verified_teaser_starts(raw, sha256(raw).hexdigest())
        self.assertFalse(_TEASER_STARTS_CACHE)

    def test_cache_is_bounded_and_drops_oldest_digest(self):
        first_digest = None
        for number in range(_TEASER_STARTS_CACHE_LIMIT + 1):
            raw = card(f"hz45_{number}", "ab Montag, 02.11.26").encode()
            digest = sha256(raw).hexdigest()
            if first_digest is None:
                first_digest = digest
            _verified_teaser_starts(raw, digest)
        self.assertEqual(len(_TEASER_STARTS_CACHE), _TEASER_STARTS_CACHE_LIMIT)
        self.assertNotIn(first_digest, _TEASER_STARTS_CACHE)
