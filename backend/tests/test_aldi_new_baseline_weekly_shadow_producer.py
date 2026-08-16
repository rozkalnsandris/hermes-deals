from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import aldi_new_baseline_weekly_shadow_producer as producer


def offer(start: str, price: float = 1.0) -> dict[str, object]:
    return {
        "currentPrice": {"priceValue": price},
        "promotionPrices": [{"validFromLocalDate": start}],
    }


class AldiWeeklyShadowProducerTest(unittest.TestCase):
    def test_extracts_only_priced_exact_object_ids(self):
        payload = {
            "props": {
                "pageProps": {
                    "apiData": [
                        [
                            "OFFER_GET",
                            {
                                "res": {
                                    "algoliaDataMap": {
                                        "offer-1": {
                                            "objectID": "offer-1",
                                            "currentPrice": {"priceValue": 1.99},
                                        },
                                        "offer-2": {
                                            "objectID": "offer-2",
                                            "currentPrice": None,
                                        },
                                    }
                                }
                            },
                        ]
                    ]
                }
            }
        }
        html = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'
        rows = producer._offer_map(html)
        self.assertEqual(list(rows), ["offer-1"])

    def test_object_id_mismatch_fails_closed(self):
        payload = {
            "props": {
                "pageProps": {
                    "apiData": [
                        [
                            "OFFER_GET",
                            {
                                "res": {
                                    "algoliaDataMap": {
                                        "offer-1": {
                                            "objectID": "different",
                                            "currentPrice": {"priceValue": 1},
                                        }
                                    }
                                }
                            },
                        ]
                    ]
                }
            }
        }
        html = f'<script id="__NEXT_DATA__">{json.dumps(payload)}</script>'
        with self.assertRaisesRegex(
            producer.ProducerError,
            "objectID/map-key mismatch",
        ):
            producer._offer_map(html)

    def test_select_week_ignores_long_lived_outlier_family(self):
        rows = {
            "week-a": offer("2026-08-17", 1.0),
            "week-b": offer("2026-08-20", 2.0),
            "outlier": offer("2026-11-02", 3.0),
        }
        selected, iso_week, valid_from, valid_until = producer._select_week(
            rows,
            datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(set(selected), {"week-a", "week-b"})
        self.assertEqual(iso_week, "2026-W34")
        self.assertEqual(valid_from.isoformat(), "2026-08-17")
        self.assertEqual(valid_until.isoformat(), "2026-08-23")
        self.assertEqual((valid_until - valid_from).days, 6)

    def test_sunday_tie_prefers_family_starting_next_day(self):
        rows = {
            "old": offer("2026-08-10"),
            "next": offer("2026-08-17"),
        }
        selected, iso_week, _, _ = producer._select_week(
            rows,
            datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(set(selected), {"next"})
        self.assertEqual(iso_week, "2026-W34")

    def test_missing_validity_start_is_not_promoted(self):
        rows = {
            "undated": {
                "currentPrice": {"priceValue": 1.0},
                "promotionPrices": [],
            }
        }
        with self.assertRaisesRegex(
            producer.ProducerError,
            "defensible validity start",
        ):
            producer._select_week(
                rows,
                datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
            )

    def test_candidate_id_is_gate_b_safe_and_deterministic(self):
        first = producer._candidate_id("ABC/Offer?123")
        second = producer._candidate_id("ABC/Offer?123")
        self.assertEqual(first, second)
        self.assertRegex(first, r"^aldi:[0-9a-f]{32}$")

    def test_request_is_hash_bound_and_write_authority_false(self):
        capture = {
            "gate_a_input": {"a": 1},
            "gate_b_input": {"b": 2},
            "gate_c_input": {"c": 3},
            "execution_evidence": {"d": 4},
        }
        with tempfile.TemporaryDirectory() as tmp:
            request_dir = Path(tmp) / "request"
            digest = producer.write_request(
                capture=capture,
                authorized_main_sha="a" * 40,
                request_dir=request_dir,
            )
            raw = (request_dir / "request.json").read_bytes()
            self.assertEqual(digest, sha256(raw).hexdigest())
            request = json.loads(raw)
            self.assertFalse(request["production_deploy_authorized"])
            self.assertFalse(request["production_canary_authorized"])
            self.assertFalse(request["production_database_write_authorized"])
            self.assertFalse(request["review_or_publication_write_authorized"])
            self.assertFalse(request["source_mutation_authorized"])
            self.assertFalse(request["automatic_schedule"])

    def test_invalid_main_sha_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(
                producer.ProducerError,
                "main SHA invalid",
            ):
                producer.write_request(
                    capture={
                        "gate_a_input": {},
                        "gate_b_input": {},
                        "gate_c_input": {},
                        "execution_evidence": {},
                    },
                    authorized_main_sha="main",
                    request_dir=Path(tmp) / "request",
                )


if __name__ == "__main__":
    unittest.main()
