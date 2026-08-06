from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_weekly_gate_c_shadow_replay_preflight.py"
GATE_B_PLAN = ROOT / "config" / "aldi-weekly-gate-b-replay-plan-31105044968.json"
SPEC = importlib.util.spec_from_file_location(
    "aldi_weekly_gate_c_shadow_replay_preflight", TOOL
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AldiWeeklyGateCShadowReplayPreflightTest(unittest.TestCase):
    def load_gate_b(self) -> tuple[dict[str, object], dict[str, object]]:
        return MODULE.load_gate_b_plan(GATE_B_PLAN)

    def a21_summary(self) -> dict[str, object]:
        return {
            "sha256": MODULE.EXPECTED_A21_PROJECTION_SHA256,
            "row_count": 519,
            "publication_counts": dict(MODULE.EXPECTED_PUBLICATION_COUNTS),
            "offer_identity_sha256": "a" * 64,
        }

    def legacy_bundle(self) -> dict[str, object]:
        mappings = []
        reverse = []
        for index in range(400):
            status = "auto_candidate" if index < 346 else "review_required"
            page = (index % 41) + 1
            card_id = f"preview:p{page:03d}:c{index + 1:03d}"
            offer_key = f"preview:{1000000 + index}"
            mappings.append(
                {
                    "offer_key": offer_key,
                    "publication_status": status,
                    "match_status": "matched",
                    "match_method": "explicit_offer_id",
                    "card_id": card_id,
                    "score": None,
                    "candidate_card_ids": [card_id],
                    "display_title": f"Offer {index}",
                    "price_eur": "1.00",
                    "review_reasons": ["frozen_review"]
                    if status == "review_required"
                    else [],
                    "source_offer_id": str(1000000 + index),
                    "source_page": "preview",
                    "title_tokens": ["offer", str(index)],
                    "brand_tokens": [],
                }
            )
            reverse.append(
                {
                    "card_id": card_id,
                    "source_page": "preview",
                    "page_number": page,
                    "scope": "in_scope" if status == "auto_candidate" else "review",
                    "matched_offer_keys": [offer_key],
                    "unmatched_reason": "",
                    "unexplained": False,
                }
            )
        summary = {
            "schema_version": 1,
            "strategy": "aldi_a31_deterministic_bidirectional_parity_v1",
            "target_counts": dict(MODULE.EXPECTED_TARGET_COUNTS),
            "target_candidate_count": 400,
            "matched_candidate_count": 400,
            "review_unmatched_count": 0,
            "blocked_candidate_count": 0,
            "card_count": 400,
            "in_scope_or_review_card_count": 400,
            "unexplained_card_count": 0,
            "blocker_count": 0,
            "mapping_sha256": MODULE.canonical_sha(mappings),
            "reverse_coverage_sha256": MODULE.canonical_sha(reverse),
            "result": "pass",
            "shadow_only": True,
            "production_eligible": False,
            "production_apply_authorized": False,
            "database_write_performed": False,
            "deployment_performed": False,
            "collector_executed": False,
            "automatic_approval_count": 0,
            "automatic_publication_count": 0,
        }
        return {
            "schema_version": 1,
            "mode": MODULE.LEGACY_BUNDLE_MODE,
            "input_projection_sha256": MODULE.EXPECTED_A21_PROJECTION_SHA256,
            "summary": summary,
            "offer_to_card_mapping": mappings,
            "reverse_card_coverage": reverse,
            "blockers": [],
        }

    def validated_legacy(self) -> dict[str, object]:
        bundle = self.legacy_bundle()
        return MODULE.validate_legacy_parity_bundle(
            bundle, file_sha256=MODULE.canonical_sha(bundle)
        )

    def page3_ledger(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": MODULE.PAGE3_MODE,
            "page_number": 3,
            "page_sha256": MODULE.EXPECTED_PAGE3_SHA256,
            "extraction_result": "complete",
            "candidate_count": 2,
            "candidates": [
                {
                    "candidate_id": "page3:produce:001",
                    "card_id": "current:p003:c001",
                    "publication_status": "review_required",
                    "review_reasons": ["fresh_weekly_page_requires_visual_review"],
                    "production_eligible": False,
                    "automatic_approval_allowed": False,
                    "automatic_publication_allowed": False,
                },
                {
                    "candidate_id": "page3:produce:002",
                    "card_id": "current:p003:c002",
                    "publication_status": "review_required",
                    "review_reasons": ["fresh_weekly_page_requires_visual_review"],
                    "production_eligible": False,
                    "automatic_approval_allowed": False,
                    "automatic_publication_allowed": False,
                },
            ],
            "shadow_only": True,
            "production_eligible": False,
            "candidate_creation_performed": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "automatic_approval_performed": False,
            "automatic_publication_performed": False,
        }

    def validated_page3(self) -> dict[str, object]:
        ledger = self.page3_ledger()
        return MODULE.validate_page3_ledger(
            ledger, file_sha256=MODULE.canonical_sha(ledger)
        )

    def test_exact_merged_gate_b_plan_is_accepted(self) -> None:
        plan, validated = self.load_gate_b()

        self.assertEqual(plan["decision"], "READY_FOR_SHADOW_REPLAY")
        self.assertEqual(len(validated["manifest"]), 41)
        self.assertEqual(len(validated["carry_forward_mappings"]), 39)

    def test_exact_gate_b_without_missing_evidence_waits_explicitly(self) -> None:
        _, validated = self.load_gate_b()

        result = MODULE.build_result(validated)

        self.assertEqual(result["decision"], "WAIT_FOR_VISUAL_LEDGER")
        self.assertEqual(
            result["missing_inputs"],
            [
                "a21_adjudicated_projection",
                "completed_legacy_a31_parity_bundle",
                "page3_fresh_shadow_extraction_ledger",
            ],
        )
        self.assertFalse(result["candidate_parity_claimed"])
        self.assertFalse(result["production_eligible"])

    def test_gate_b_fingerprint_only_object_is_rejected(self) -> None:
        minimal = {
            "schema_version": 1,
            "mode": MODULE.GATE_B_MODE,
            "replay_fingerprint": MODULE.EXPECTED_GATE_B_FINGERPRINT,
        }

        with self.assertRaisesRegex(MODULE.GateCError, "Gate B plan SHA256 mismatch"):
            MODULE.validate_gate_b_plan(minimal, file_sha256="0" * 64)

    def test_gate_b_work_package_keeps_page_41_excluded(self) -> None:
        _, validated = self.load_gate_b()

        result = MODULE.build_result(validated)
        pages = {
            row["new_current_page"]: row for row in result["work_package"]["pages"]
        }

        self.assertEqual(pages[41]["action"], "exclude_non_offer_informational")
        self.assertEqual(pages[41]["candidate_count"], 0)
        self.assertEqual(pages[3]["action"], "fresh_shadow_extraction")
        self.assertEqual(len(result["work_package"]["pages"]), 41)

    def test_gate_b_moved_pages_are_preserved(self) -> None:
        _, validated = self.load_gate_b()
        moved = {
            (row["old_preview_page"], row["new_current_page"])
            for row in validated["carry_forward_mappings"]
            if row["method"] == "exact_moved_page"
        }

        self.assertEqual(moved, {(3, 4), (4, 5), (5, 37)})

    def test_completed_legacy_parity_bundle_is_accepted(self) -> None:
        validated = self.validated_legacy()

        self.assertEqual(validated["target_counts"], MODULE.EXPECTED_TARGET_COUNTS)
        self.assertEqual(validated["card_count"], 400)
        self.assertEqual(
            sum(
                len(rows) for rows in validated["preview_card_bindings"].values()
            ),
            400,
        )

    def test_empty_a31_template_is_not_a_completed_bundle(self) -> None:
        empty_template = {
            "schema_version": 1,
            "source_page_set_sha256": "0" * 64,
            "cards": [],
            "candidate_hints": [],
        }

        with self.assertRaisesRegex(
            MODULE.GateCError, "unexpected legacy parity bundle mode"
        ):
            MODULE.validate_legacy_parity_bundle(
                empty_template,
                file_sha256=MODULE.canonical_sha(empty_template),
            )

    def test_legacy_bundle_with_blocker_is_rejected(self) -> None:
        bundle = self.legacy_bundle()
        bundle["blockers"] = [{"type": "no_match"}]

        with self.assertRaisesRegex(MODULE.GateCError, "blockers must be empty"):
            MODULE.validate_legacy_parity_bundle(
                bundle,
                file_sha256=MODULE.canonical_sha(bundle),
            )

    def test_exact_page3_review_only_ledger_is_accepted(self) -> None:
        validated = self.validated_page3()

        self.assertEqual(validated["candidate_count"], 2)
        self.assertEqual(
            {row["card_id"] for row in validated["candidates"]},
            {"current:p003:c001", "current:p003:c002"},
        )

    def test_page3_wrong_sha_is_rejected(self) -> None:
        ledger = self.page3_ledger()
        ledger["page_sha256"] = "0" * 64

        with self.assertRaisesRegex(
            MODULE.GateCError, "page 3 ledger SHA binding mismatch"
        ):
            MODULE.validate_page3_ledger(
                ledger,
                file_sha256=MODULE.canonical_sha(ledger),
            )

    def test_page3_production_eligible_candidate_is_rejected(self) -> None:
        ledger = self.page3_ledger()
        ledger["candidates"][0]["production_eligible"] = True

        with self.assertRaisesRegex(
            MODULE.GateCError, "cannot be production-eligible"
        ):
            MODULE.validate_page3_ledger(
                ledger,
                file_sha256=MODULE.canonical_sha(ledger),
            )

    def test_complete_inputs_become_ready(self) -> None:
        _, validated = self.load_gate_b()
        legacy = self.validated_legacy()
        page3 = self.validated_page3()

        result = MODULE.build_result(
            validated,
            a21=self.a21_summary(),
            legacy=legacy,
            page3=page3,
        )

        self.assertEqual(result["decision"], "READY_FOR_SHADOW_REPLAY")
        self.assertEqual(result["missing_inputs"], [])
        self.assertTrue(result["candidate_parity_claimed"])
        self.assertEqual(
            len(result["work_package"]["carried_card_bindings"]),
            382,
        )
        self.assertEqual(
            len(result["work_package"]["fresh_page3_candidates"]),
            2,
        )
        self.assertEqual(len(result["identity"]["replay_identity_sha256"]), 64)
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["promotion_ready"])

    def test_exact_complete_prior_result_becomes_no_op(self) -> None:
        _, validated = self.load_gate_b()
        legacy = self.validated_legacy()
        page3 = self.validated_page3()
        first = MODULE.build_result(
            validated,
            a21=self.a21_summary(),
            legacy=legacy,
            page3=page3,
        )

        second = MODULE.build_result(
            validated,
            a21=self.a21_summary(),
            legacy=legacy,
            page3=page3,
            prior=first,
        )

        self.assertEqual(second["decision"], "NO_OP")
        self.assertEqual(
            second["identity"]["replay_identity_sha256"],
            first["identity"]["replay_identity_sha256"],
        )

    def test_wait_result_cannot_be_used_as_no_op_prior(self) -> None:
        _, validated = self.load_gate_b()
        waiting = MODULE.build_result(validated)

        with self.assertRaisesRegex(
            MODULE.GateCError, "prior Gate C result is not complete"
        ):
            MODULE.build_result(validated, prior=waiting)

    def test_unsafe_prior_result_is_rejected(self) -> None:
        _, validated = self.load_gate_b()
        legacy = self.validated_legacy()
        page3 = self.validated_page3()
        prior = MODULE.build_result(
            validated,
            a21=self.a21_summary(),
            legacy=legacy,
            page3=page3,
        )
        prior["safety"]["candidate_creation_authorized"] = True

        with self.assertRaisesRegex(MODULE.GateCError, "prior Gate C safety mismatch"):
            MODULE.build_result(
                validated,
                a21=self.a21_summary(),
                legacy=legacy,
                page3=page3,
                prior=prior,
            )

    def test_output_is_create_only_and_idempotent(self) -> None:
        _, validated = self.load_gate_b()
        result = MODULE.build_result(validated)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gate-c.json"
            self.assertEqual(MODULE.write_result(path, result), "created")
            self.assertEqual(MODULE.write_result(path, result), "unchanged")
            changed = deepcopy(result)
            changed["decision"] = "BLOCKED"
            with self.assertRaisesRegex(
                MODULE.GateCError, "existing Gate C output differs"
            ):
                MODULE.write_result(path, changed)

    def test_duplicate_a21_offer_identity_fails_closed(self) -> None:
        row = {
            "source_page": "preview",
            "source_offer_id": "1001",
            "publication": {"status": "blocked_out_of_scope"},
        }
        rows = [deepcopy(row) for _ in range(519)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projection.jsonl"
            path.write_text(
                "".join(
                    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
                    for value in rows
                ),
                encoding="utf-8",
            )
            original = MODULE.EXPECTED_A21_PROJECTION_SHA256
            MODULE.EXPECTED_A21_PROJECTION_SHA256 = MODULE.sha_file(path)
            try:
                with self.assertRaisesRegex(
                    MODULE.GateCError, "duplicate A2.1 offer identity"
                ):
                    MODULE.load_a21_projection(path)
            finally:
                MODULE.EXPECTED_A21_PROJECTION_SHA256 = original

    def test_a21_publication_count_drift_fails_closed(self) -> None:
        rows = []
        for index in range(519):
            rows.append(
                {
                    "source_page": "preview",
                    "source_offer_id": str(index),
                    "publication": {"status": "blocked_out_of_scope"},
                }
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projection.jsonl"
            path.write_text(
                "".join(
                    json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
                    for value in rows
                ),
                encoding="utf-8",
            )
            original = MODULE.EXPECTED_A21_PROJECTION_SHA256
            MODULE.EXPECTED_A21_PROJECTION_SHA256 = MODULE.sha_file(path)
            try:
                with self.assertRaisesRegex(
                    MODULE.GateCError, "publication count drift"
                ):
                    MODULE.load_a21_projection(path)
            finally:
                MODULE.EXPECTED_A21_PROJECTION_SHA256 = original


if __name__ == "__main__":
    unittest.main()
