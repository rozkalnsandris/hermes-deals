from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_a31_offer_page_parity.py"
SPEC = importlib.util.spec_from_file_location("aldi_a31_offer_page_parity", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def projection_row(
    offer_id: str,
    *,
    source_page: str = "current",
    status: str = "auto_candidate",
    title: str = "MILFINA Frische Vollmilch",
    brand: str = "MILFINA",
    name: str = "Frische Vollmilch",
    price: str = "1.19",
    review_reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "source_page": source_page,
        "source_offer_id": offer_id,
        "identity": {
            "display_title_candidate": title,
            "brand_raw": brand,
            "name_raw": name,
        },
        "pricing": {"price_eur": price},
        "publication": {
            "status": status,
            "review_reasons": review_reasons or [],
        },
    }


def card(
    card_id: str,
    *,
    source_page: str = "current",
    page_number: int = 1,
    title: str = "MILFINA Frische Vollmilch",
    brand: str = "MILFINA",
    price: str = "1.19",
    scope: str = "in_scope",
    explicit_offer_ids: list[str] | None = None,
    unmatched_reason: str = "",
) -> dict[str, object]:
    return {
        "card_id": card_id,
        "source_page": source_page,
        "page_number": page_number,
        "region": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.2},
        "scope": scope,
        "title": title,
        "brand": brand,
        "price_eur": price,
        "explicit_offer_ids": explicit_offer_ids or [],
        "unmatched_reason": unmatched_reason,
        "notes": "",
    }


def page_manifest() -> dict[str, object]:
    return {
        "rows": [
            {
                "label": label,
                "page_number": page,
                "format": "jpeg",
                "bytes": 50_000,
                "sha256": sha256(f"{label}:{page}".encode()).hexdigest(),
            }
            for label, count in MODULE.EXPECTED_PAGE_COUNTS.items()
            for page in range(1, count + 1)
        ]
    }


class AldiA31InputTest(unittest.TestCase):
    def test_projection_sha_and_publication_counts_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "projection.jsonl"
            rows = [
                projection_row("1"),
                projection_row(
                    "2",
                    status="review_required",
                    review_reasons=["manual_scope_boundary"],
                ),
                {
                    **projection_row("3"),
                    "publication": {
                        "status": "blocked_out_of_scope",
                        "review_reasons": [],
                    },
                },
            ]
            path.write_text(
                "\n".join(
                    json.dumps(row, sort_keys=True, separators=(",", ":"))
                    for row in rows
                )
                + "\n",
                encoding="utf-8",
            )
            loaded = MODULE.load_projection(
                path,
                expected_sha256=MODULE.sha_file(path),
                expected_publication_counts={
                    "auto_candidate": 1,
                    "review_required": 1,
                    "blocked_out_of_scope": 1,
                },
            )
            self.assertEqual(len(loaded), 3)
            with self.assertRaisesRegex(MODULE.AldiA31Error, "SHA mismatch"):
                MODULE.load_projection(
                    path,
                    expected_sha256="0" * 64,
                    expected_publication_counts={
                        "auto_candidate": 1,
                        "review_required": 1,
                        "blocked_out_of_scope": 1,
                    },
                )

    def test_all_90_frozen_pages_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pages.json"
            payload = page_manifest()
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = MODULE.validate_page_manifest(path)
            self.assertEqual(result["total_pages"], 90)
            payload["rows"] = payload["rows"][:-1]
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.AldiA31Error, "incomplete"):
                MODULE.validate_page_manifest(path)

    def test_card_ledger_is_bound_to_page_set_and_stable_regions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages_path = root / "pages.json"
            pages_path.write_text(json.dumps(page_manifest()), encoding="utf-8")
            pages = MODULE.validate_page_manifest(pages_path)
            ledger_path = root / "ledger.json"
            ledger_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_page_set_sha256": pages["page_set_sha256"],
                        "cards": [card("current:p001:c001")],
                    }
                ),
                encoding="utf-8",
            )
            rows = MODULE.validate_card_ledger(
                ledger_path,
                page_set_sha256=pages["page_set_sha256"],
            )
            self.assertEqual(rows[0]["card_id"], "current:p001:c001")
            data = json.loads(ledger_path.read_text())
            data["source_page_set_sha256"] = "0" * 64
            ledger_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.AldiA31Error, "not bound"):
                MODULE.validate_card_ledger(
                    ledger_path,
                    page_set_sha256=pages["page_set_sha256"],
                )


class AldiA31ParityTest(unittest.TestCase):
    def test_explicit_offer_identity_wins(self) -> None:
        result = MODULE.run_parity(
            [projection_row("100")],
            [card("current:p001:c001", explicit_offer_ids=["100"])],
            expected_target_counts={"auto_candidate": 1},
        )
        self.assertEqual(result["summary"]["result"], "pass")
        self.assertEqual(
            result["mappings"][0]["match_method"],
            "explicit_offer_id",
        )

    def test_unique_title_brand_price_match_is_accepted(self) -> None:
        result = MODULE.run_parity(
            [projection_row("101")],
            [
                card("current:p001:c001"),
                card(
                    "current:p001:c002",
                    title="GUT BIO Apfelsaft",
                    brand="GUT BIO",
                    price="1.59",
                ),
            ],
            expected_target_counts={"auto_candidate": 1},
        )
        self.assertEqual(result["summary"]["result"], "blocked")
        self.assertEqual(result["summary"]["matched_candidate_count"], 1)
        self.assertEqual(result["summary"]["unexplained_card_count"], 1)

        explained = [
            card("current:p001:c001"),
            card(
                "current:p001:c002",
                title="GUT BIO Apfelsaft",
                brand="GUT BIO",
                price="1.59",
                unmatched_reason="out-of-corpus regional card",
            ),
        ]
        result = MODULE.run_parity(
            [projection_row("101")],
            explained,
            expected_target_counts={"auto_candidate": 1},
        )
        self.assertEqual(result["summary"]["result"], "pass")
        self.assertEqual(
            result["mappings"][0]["match_method"],
            "conservative_title_brand_price",
        )

    def test_ambiguous_auto_candidate_fails_closed(self) -> None:
        result = MODULE.run_parity(
            [projection_row("102")],
            [
                card("current:p001:c001"),
                card("current:p001:c002"),
            ],
            expected_target_counts={"auto_candidate": 1},
        )
        self.assertEqual(result["summary"]["result"], "blocked")
        self.assertTrue(
            any(item["type"] == "ambiguous_match" for item in result["blockers"])
        )

    def test_unmatched_review_row_requires_documented_reason(self) -> None:
        allowed = MODULE.run_parity(
            [
                projection_row(
                    "103",
                    status="review_required",
                    title="Ambiguous boundary item",
                    review_reasons=["personal_hygiene"],
                )
            ],
            [],
            expected_target_counts={"review_required": 1},
        )
        self.assertEqual(allowed["summary"]["result"], "pass")
        self.assertEqual(
            allowed["mappings"][0]["match_status"],
            "review_unmatched",
        )

        blocked = MODULE.run_parity(
            [
                projection_row(
                    "104",
                    status="review_required",
                    title="Ambiguous boundary item",
                    review_reasons=[],
                )
            ],
            [],
            expected_target_counts={"review_required": 1},
        )
        self.assertEqual(blocked["summary"]["result"], "blocked")

    def test_reverse_coverage_rejects_unexplained_in_scope_card(self) -> None:
        result = MODULE.run_parity(
            [],
            [card("current:p001:c001")],
            expected_target_counts={},
        )
        self.assertEqual(result["summary"]["unexplained_card_count"], 1)
        self.assertEqual(result["summary"]["result"], "blocked")

    def test_result_hashes_are_deterministic_across_input_order(self) -> None:
        rows = [projection_row("2"), projection_row("1")]
        cards = [
            card("current:p001:c002", explicit_offer_ids=["2"]),
            card("current:p001:c001", explicit_offer_ids=["1"]),
        ]
        first = MODULE.run_parity(
            rows,
            cards,
            expected_target_counts={"auto_candidate": 2},
        )
        second = MODULE.run_parity(
            list(reversed(rows)),
            list(reversed(cards)),
            expected_target_counts={"auto_candidate": 2},
        )
        self.assertEqual(first["summary"]["mapping_sha256"], second["summary"]["mapping_sha256"])
        self.assertEqual(
            first["summary"]["reverse_coverage_sha256"],
            second["summary"]["reverse_coverage_sha256"],
        )
        self.assertEqual(first["mappings"], second["mappings"])
        self.assertEqual(first["reverse_coverage"], second["reverse_coverage"])


class AldiA31TemplateAndSafetyTest(unittest.TestCase):
    def test_template_accounts_for_target_rows_and_all_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pages.json"
            path.write_text(json.dumps(page_manifest()), encoding="utf-8")
            pages = MODULE.validate_page_manifest(path)
            template = MODULE.build_template(
                [
                    projection_row("1"),
                    projection_row(
                        "2",
                        status="review_required",
                        review_reasons=["manual"],
                    ),
                    {
                        **projection_row("3"),
                        "publication": {
                            "status": "blocked_out_of_scope",
                            "review_reasons": [],
                        },
                    },
                ],
                pages,
            )
            self.assertEqual(len(template["pages"]), 90)
            self.assertEqual(len(template["candidate_hints"]), 2)
            self.assertEqual(
                template["source_page_set_sha256"],
                pages["page_set_sha256"],
            )

    def test_runner_contains_no_production_actions(self) -> None:
        text = (
            ROOT / "tools" / "run-hermes-deals-aldi-a31-parity-v01.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("docker", text)
        self.assertNotIn("psql", text)
        self.assertNotIn("systemctl", text)
        self.assertNotIn("git commit", text)
        self.assertNotIn("git push", text)
        self.assertIn("production_database_write=false", text)
        self.assertIn("automatic_publication=false", text)


if __name__ == "__main__":
    unittest.main()
