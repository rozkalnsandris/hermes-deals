from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidl_weekly_one_shot import find_corpus_match, source_readiness


def source_payload(*, date_time: str, flyer_id: str = "flyer-1") -> bytes:
    return json.dumps(
        {
            "dateTime": date_time,
            "flyer": {
                "id": flyer_id,
                "flyerUrlAbsolute": (
                    "https://www.lidl.de/l/prospekte/aktionsprospekt-test/ar/21?_ab=1"
                ),
                "hiResPdfUrl": (
                    "https://assets.leaflets.schwarz/leaflets/pdfs/flyer-1/test.pdf"
                ),
                "offerStartDate": "2026-08-03",
                "offerEndDate": "2026-08-08",
                "regions": [{"code": "21"}, {"code": "7"}],
                "pages": [{"links": []}, {"links": []}],
            },
        },
        sort_keys=True,
    ).encode("utf-8")


class LidlWeeklyOneShotTest(unittest.TestCase):
    def test_discoverable_false_without_products_waits_for_source(self) -> None:
        raw = json.dumps(
            {
                "flyer": {
                    "discoverable": False,
                    "title": "NonFood",
                    "pages": [{"links": []}],
                }
            }
        ).encode()
        row = source_readiness(raw)
        self.assertEqual(row["state"], "WAIT_SOURCE")
        self.assertEqual(row["reason"], "discoverable_false_without_product_links")
        self.assertTrue(row["nonfood_signal"])

    def test_normal_product_payload_is_available(self) -> None:
        raw = json.dumps(
            {
                "flyer": {
                    "discoverable": True,
                    "pages": [
                        {
                            "links": [
                                {
                                    "displayType": "product",
                                    "productDetails": {"productId": "p1"},
                                }
                            ]
                        }
                    ],
                }
            }
        ).encode()
        row = source_readiness(raw)
        self.assertEqual(row["state"], "SOURCE_AVAILABLE")
        self.assertEqual(row["product_link_count"], 1)

    def test_invalid_json_blocks_source_drift(self) -> None:
        row = source_readiness(b"not-json")
        self.assertEqual(row["state"], "BLOCKED_SOURCE_DRIFT")

    def test_exact_corpus_identity_and_latest_scan(self) -> None:
        with TemporaryDirectory() as temporary:
            corpus = Path(temporary)
            flyer = corpus / "flyers" / "family-next"
            (flyer / "scans" / "scan-0001").mkdir(parents=True)
            (flyer / "scans" / "scan-0003").mkdir(parents=True)
            pdf = b"%PDF-exact"
            raw = source_payload(date_time="2026-07-28T10:00:00+00:00")
            (flyer / "source.pdf").write_bytes(pdf)
            (flyer / "source.json").write_bytes(raw)
            match = find_corpus_match(
                corpus,
                pdf_sha256=sha256(pdf).hexdigest(),
                live_source_json=raw,
            )
            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.flyer_key, "family-next")
            self.assertEqual(match.scan, "scan-0003")

    def test_nonmatching_corpus_returns_none(self) -> None:
        with TemporaryDirectory() as temporary:
            corpus = Path(temporary)
            (corpus / "flyers").mkdir()
            self.assertIsNone(
                find_corpus_match(
                    corpus,
                    pdf_sha256="0" * 64,
                    live_source_json=source_payload(
                        date_time="2026-07-30T10:00:00+00:00"
                    ),
                )
            )

    def test_volatile_raw_refresh_is_accepted_for_same_stable_identity(self) -> None:
        with TemporaryDirectory() as temporary:
            corpus = Path(temporary)
            flyer = corpus / "flyers" / "family-next"
            flyer.mkdir(parents=True)
            pdf = b"%PDF-stable"
            corpus_raw = source_payload(date_time="2026-07-28T10:00:00+00:00")
            live_raw = source_payload(date_time="2026-07-30T15:20:13+00:00")
            (flyer / "source.pdf").write_bytes(pdf)
            (flyer / "source.json").write_bytes(corpus_raw)
            match = find_corpus_match(
                corpus,
                pdf_sha256=sha256(pdf).hexdigest(),
                live_source_json=live_raw,
            )
            self.assertIsNotNone(match)
            assert match is not None
            self.assertTrue(match.raw_refresh)
            self.assertNotEqual(match.source_raw_sha256, match.live_raw_sha256)
            self.assertEqual(len(match.stable_source_identity_sha256), 64)

    def test_same_pdf_with_different_stable_identity_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            corpus = Path(temporary)
            flyer = corpus / "flyers" / "family-next"
            flyer.mkdir(parents=True)
            pdf = b"%PDF-stable"
            corpus_raw = source_payload(date_time="2026-07-28T10:00:00+00:00")
            live_raw = source_payload(
                date_time="2026-07-30T15:20:13+00:00",
                flyer_id="different-flyer",
            )
            (flyer / "source.pdf").write_bytes(pdf)
            (flyer / "source.json").write_bytes(corpus_raw)
            with self.assertRaises(RuntimeError):
                find_corpus_match(
                    corpus,
                    pdf_sha256=sha256(pdf).hexdigest(),
                    live_source_json=live_raw,
                )

    def test_duplicate_source_identity_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            corpus = Path(temporary)
            pdf = b"%PDF-duplicate"
            raw = source_payload(date_time="2026-07-28T10:00:00+00:00")
            for key in ("a", "b"):
                flyer = corpus / "flyers" / key
                flyer.mkdir(parents=True)
                (flyer / "source.pdf").write_bytes(pdf)
                (flyer / "source.json").write_bytes(raw)
            with self.assertRaises(RuntimeError):
                find_corpus_match(
                    corpus,
                    pdf_sha256=sha256(pdf).hexdigest(),
                    live_source_json=raw,
                )


if __name__ == "__main__":
    unittest.main()
