from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lidl_weekly_staging import (
    StagingError,
    EXIT_CODES,
    _binding_change_summary,
    _canonical_json_bytes,
    _identity_digest,
    _parser_input_identity,
    _product_binding_digest,
    _stable_source_identity,
    _validate_review_profile,
    _validate_source_review,
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


def profile_payload(*, pdf_sha256: str = "a" * 64) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "independent_page_role_reviewed_product_audit_in_progress",
        "target_kind": "weekly_physical_deals",
        "target_pages": [1],
        "baseline_pages": [2],
        "excluded_page_roles": {
            "editorial": [3],
            "online_nonfood": [4],
        },
        "reference_expectations": {
            "status": "provisional_until_full_card_audit",
            "target_page_count": 1,
        },
        "unit_basis_reviews": [],
        "source": (
            "Independent visual page-role audit of exact immutable PDF "
            + pdf_sha256
        ),
        "note": "Page roles only; product truth remains independently reviewed.",
    }


def review_payload(
    *,
    decision: str = "approve_parser_input_refresh",
    scope: str = "authoritative_staging_scan_only",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "decision": decision,
        "scope": scope,
        "approved_by": "Andris Rožkalns",
        "approved_at": "2026-07-30T21:54:00+02:00",
        "note": "Approved exact source refresh for staging scan only.",
        "flyer_key": "20260803-20260808-r21-aaaaaaaaaaaa",
        "pdf_sha256": "a" * 64,
        "reference_input": {
            "parser_input_identity_sha256": "b" * 64,
            "product_binding_sha256": "c" * 64,
            "product_binding_count": 1,
        },
        "approved_live_input": {
            "parser_input_identity_sha256": "d" * 64,
            "product_binding_sha256": "e" * 64,
            "product_binding_count": 2,
        },
        "observed_changes": {
            "binding_added": 1,
            "binding_removed": 0,
            "binding_title_changed": 1,
        },
        "permissions": {
            "staging_scan": True,
            "corpus_write": False,
            "db_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "systemd_change": False,
        },
    }


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

    def _validate_review(self, payload: dict[str, object]) -> tuple[dict[str, object], str]:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "source-review.json"
            path.write_bytes(_canonical_json_bytes(payload))
            return _validate_source_review(
                source_review_file=path,
                flyer_key="20260803-20260808-r21-aaaaaaaaaaaa",
                pdf_sha256="a" * 64,
                reference_input={
                    "parser_input_identity_sha256": "b" * 64,
                    "product_binding_sha256": "c" * 64,
                    "product_binding_count": 1,
                },
                live_parser_input_sha256="d" * 64,
                live_product_binding_sha256="e" * 64,
                live_product_binding_count=2,
                binding_changes={
                    "binding_added": 1,
                    "binding_removed": 0,
                    "binding_title_changed": 1,
                },
            )

    def test_source_review_exact_approval_is_accepted(self) -> None:
        payload = review_payload()
        review, digest = self._validate_review(payload)
        self.assertEqual(review, payload)
        self.assertEqual(len(digest), 64)

    def test_source_review_digest_is_key_order_independent(self) -> None:
        payload = review_payload()
        reversed_payload = dict(reversed(list(payload.items())))
        first = self._validate_review(payload)[1]
        second = self._validate_review(reversed_payload)[1]
        self.assertEqual(first, second)

    def test_source_review_rejects_nonapproval_decision(self) -> None:
        with self.assertRaises(StagingError):
            self._validate_review(review_payload(decision="reject"))

    def test_source_review_rejects_unsafe_scope(self) -> None:
        with self.assertRaises(StagingError):
            self._validate_review(review_payload(scope="corpus_promotion"))

    def test_source_review_rejects_live_input_mismatch(self) -> None:
        payload = review_payload()
        payload["approved_live_input"]["product_binding_count"] = 3
        with self.assertRaises(StagingError):
            self._validate_review(payload)

    def _validate_profile(
        self,
        payload: dict[str, object],
    ) -> tuple[dict[str, object], bytes, str]:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "review-profile.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return _validate_review_profile(
                review_profile_file=path,
                pdf_sha256="a" * 64,
                page_count=4,
            )

    def test_review_profile_exact_partition_is_accepted(self) -> None:
        payload = profile_payload()
        profile, raw, digest = self._validate_profile(payload)
        self.assertEqual(profile, payload)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(len(digest), 64)

    def test_review_profile_rejects_unreviewed_status(self) -> None:
        payload = profile_payload()
        payload["status"] = "draft"
        with self.assertRaises(StagingError):
            self._validate_profile(payload)

    def test_review_profile_rejects_overlapping_page_roles(self) -> None:
        payload = profile_payload()
        payload["baseline_pages"] = [1, 2]
        with self.assertRaises(StagingError):
            self._validate_profile(payload)

    def test_review_profile_rejects_page_partition_gap(self) -> None:
        payload = profile_payload()
        payload["excluded_page_roles"]["online_nonfood"] = []
        with self.assertRaises(StagingError):
            self._validate_profile(payload)

    def test_review_profile_rejects_source_pdf_mismatch(self) -> None:
        with self.assertRaises(StagingError):
            self._validate_profile(profile_payload(pdf_sha256="b" * 64))

    def test_review_profile_rejects_target_count_mismatch(self) -> None:
        payload = profile_payload()
        payload["reference_expectations"]["target_page_count"] = 2
        with self.assertRaises(StagingError):
            self._validate_profile(payload)

    def test_review_profile_rejects_field_set_drift(self) -> None:
        payload = profile_payload()
        payload["unexpected"] = True
        with self.assertRaises(StagingError):
            self._validate_profile(payload)

    def test_binding_change_summary_tracks_add_remove_and_title(self) -> None:
        reference = json.loads(source_payload())
        live = json.loads(source_payload())
        live["flyer"]["products"]["p1"]["title"] = "Vollmilch"
        live["flyer"]["pages"][0]["links"].append(
            {
                "left": 50,
                "top": 10,
                "width": 10,
                "height": 10,
                "productDetails": {
                    "productId": "456",
                    "title": "Butter",
                },
            }
        )
        live["flyer"]["products"]["p2"] = {
            "productId": "456",
            "title": "Butter",
        }
        summary = _binding_change_summary(
            json.dumps(reference).encode(),
            json.dumps(live).encode(),
        )
        self.assertEqual(
            summary,
            {
                "binding_added": 1,
                "binding_removed": 0,
                "binding_title_changed": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
