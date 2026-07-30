from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lidl_weekly_staging import (
    StagingError,
    EXIT_CODES,
    _identity_digest,
    _parser_input_identity,
    _product_binding_digest,
    _stable_source_identity,
    _write_bytes_once,
    product_bindings,
    staging_flyer_key,
)


def source_payload(*, raw_marker: str = "first") -> bytes:
    return json.dumps(
        {
            "dateTime": "2026-07-30T19:00:00Z",
            "warnings": ["volatile"],
            "flyer": {
                "id": "official-1",
                "flyerUrlAbsolute": (
                    "https://www.lidl.de/l/prospekte/aktionsprospekt-x/ar/21"
                ),
                "hiResPdfUrl": "https://assets.leaflets.schwarz/pdfs/source.pdf",
                "offerStartDate": "2026-08-03",
                "offerEndDate": "2026-08-08",
                "regions": [{"code": "21"}, {"code": "7"}],
                "marker": raw_marker,
                "products": {
                    "p1": {"productId": "123", "title": "Milch"}
                },
                "pages": [
                    {
                        "links": [
                            {
                                "left": 10,
                                "top": 20,
                                "width": 30,
                                "height": 40,
                                "productDetails": {
                                    "productId": "123",
                                    "title": "",
                                },
                            }
                        ]
                    }
                ],
            }
        },
        sort_keys=True,
    ).encode()


class LidlWeeklyStagingTest(unittest.TestCase):
    def test_flyer_key_is_pdf_content_addressed(self) -> None:
        self.assertEqual(
            staging_flyer_key(
                valid_from="2026-08-03",
                valid_until="2026-08-08",
                route_region="21",
                pdf_sha256="a" * 64,
            ),
            "20260803-20260808-r21-aaaaaaaaaaaa",
        )

    def test_flyer_key_rejects_short_digest(self) -> None:
        with self.assertRaises(StagingError):
            staging_flyer_key(
                valid_from="2026-08-03",
                valid_until="2026-08-08",
                route_region="21",
                pdf_sha256="a" * 12,
            )

    def test_stable_identity_ignores_volatile_raw_fields(self) -> None:
        first = _stable_source_identity(source_payload(raw_marker="first"))
        second = _stable_source_identity(source_payload(raw_marker="second"))
        self.assertEqual(first, second)
        self.assertEqual(_identity_digest(first), _identity_digest(second))

    def test_stable_identity_changes_for_official_path_drift(self) -> None:
        payload = json.loads(source_payload())
        payload["flyer"]["hiResPdfUrl"] = "https://assets.leaflets.schwarz/pdfs/other.pdf"
        first = _stable_source_identity(source_payload())
        second = _stable_source_identity(json.dumps(payload).encode())
        self.assertNotEqual(first, second)

    def test_product_bindings_normalize_percent_geometry(self) -> None:
        rows = product_bindings(source_payload())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].page, 0)
        self.assertEqual(rows[0].product_id, "123")
        self.assertEqual(rows[0].title, "Milch")
        self.assertEqual(rows[0].bbox, (0.1, 0.2, 0.4, 0.6))

    def test_parser_input_identity_ignores_top_level_volatile_fields(self) -> None:
        first = json.loads(source_payload())
        second = json.loads(source_payload())
        second["dateTime"] = "2026-07-30T20:00:00Z"
        second["warnings"] = ["different"]
        self.assertEqual(
            _parser_input_identity(json.dumps(first).encode()),
            _parser_input_identity(json.dumps(second).encode()),
        )

    def test_parser_input_identity_changes_for_semantic_refresh(self) -> None:
        self.assertNotEqual(
            _parser_input_identity(source_payload(raw_marker="first")),
            _parser_input_identity(source_payload(raw_marker="second")),
        )

    def test_product_binding_digest_changes_for_title_refresh(self) -> None:
        first = json.loads(source_payload())
        second = json.loads(source_payload())
        second["flyer"]["products"]["p1"]["title"] = "Vollmilch"
        self.assertNotEqual(
            _product_binding_digest(json.dumps(first).encode()),
            _product_binding_digest(json.dumps(second).encode()),
        )

    def test_wait_source_review_has_distinct_fail_closed_exit_code(self) -> None:
        self.assertEqual(EXIT_CODES["WAIT_SOURCE_REVIEW"], 21)
        self.assertNotEqual(
            EXIT_CODES["WAIT_SOURCE_REVIEW"],
            EXIT_CODES["WAIT_PROFILE"],
        )

    def test_write_bytes_once_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "nested" / "source.pdf"
            self.assertTrue(_write_bytes_once(path, b"same"))
            self.assertFalse(_write_bytes_once(path, b"same"))

    def test_write_bytes_once_rejects_collision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "source.pdf"
            _write_bytes_once(path, b"first")
            with self.assertRaises(StagingError):
                _write_bytes_once(path, b"second")

    def test_product_bindings_skip_invalid_geometry(self) -> None:
        payload = json.loads(source_payload())
        payload["flyer"]["pages"][0]["links"][0]["width"] = 120
        self.assertEqual(product_bindings(json.dumps(payload).encode()), ())


if __name__ == "__main__":
    unittest.main()
