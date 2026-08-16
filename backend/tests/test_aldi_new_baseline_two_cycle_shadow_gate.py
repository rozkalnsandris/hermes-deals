from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "aldi_new_baseline_two_cycle_shadow_gate.py"
SPEC = importlib.util.spec_from_file_location(
    "aldi_new_baseline_two_cycle_shadow_gate",
    TOOL_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def gate_c_binding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": MODULE.GATE_C_MODE,
        "issue_number": 682,
        "decision": "READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES",
        "replay_identity_sha256": "1" * 64,
        "deterministic_replay_verified": True,
        "duplicate_free_verified": True,
        "idempotency_verified": True,
        "second_replay_no_mutation_verified": True,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
        "promotion_ready": False,
        "weekly_shadow_cycles_complete": False,
        "identity": {
            "gate_b": {
                "baseline_id": "aldi-nord:2026-cw33:region-0:v1",
                "baseline_fingerprint": "2" * 64,
            }
        },
    }


def cycle(index: int) -> dict[str, object]:
    week = 33 + index - 1
    start_day = 10 + (index - 1) * 7
    suffix = str(index)
    return {
        "cycle_id": f"cycle-{index:02d}",
        "evidence_class": "real_weekly_shadow",
        "execution_origin": "rpi5_shadow",
        "run_id": 2000 + index,
        "observed_at_utc": f"2026-08-{start_day:02d}T08:15:00Z",
        "iso_week": f"2026-W{week:02d}",
        "campaign_id": f"aldi-nord-2026-w{week:02d}-region-0-v1",
        "valid_from": f"2026-08-{start_day:02d}",
        "valid_to": f"2026-08-{start_day + 5:02d}",
        "source_state": "available",
        "source_url": f"https://www.aldi-nord.de/angebote/aktion-mo-{start_day:02d}-08.html",
        "source_sha256": suffix * 64,
        "page_manifest_sha256": str(index + 2) * 64,
        "parser_identity_sha256": "a" * 64,
        "parity_contract_sha256": "b" * 64,
        "candidate_projection_sha256": str(index + 4) * 64,
        "card_ledger_sha256": str(index + 6) * 64,
        "semantic_output_sha256": str(index + 7) * 64,
        "evidence_artifact_sha256": str(index + 3) * 64,
        "candidate_count": 320 + index,
        "card_count": 350 + index,
        "review_routed_count": 20 + index,
        "excluded_count": 9 + index,
        "review_pending_count": 0,
        "unexplained_card_count": 0,
        "replay_new_candidate_count": 0,
        "replay_duplicate_candidate_count": 0,
        "immutable_payload_drift_count": 0,
        "shadow_state_sha256_before_replay": "c" * 64,
        "shadow_state_sha256_after_replay": "c" * 64,
        "production_database_write_count": 0,
        "review_write_count": 0,
        "publication_write_count": 0,
        "source_mutation_count": 0,
        "immutable_evidence": True,
        "production_published": False,
        "production_eligible": False,
    }


def observability() -> list[dict[str, object]]:
    return [
        {
            "state": state,
            "observed_decision": decision,
            "evidence_sha256": format(index + 10, "x")[-1] * 64,
        }
        for index, (state, decision) in enumerate(
            MODULE.REQUIRED_OBSERVABILITY.items(),
            start=1,
        )
    ]


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": MODULE.MODE,
        "issue_number": 682,
        "gate_c": gate_c_binding(),
        "cycles": [cycle(1), cycle(2)],
        "observability_proofs": observability(),
    }


class AldiNewBaselineTwoCycleShadowGateTest(unittest.TestCase):
    def test_two_consecutive_cycles_reach_canary_plan_boundary(self) -> None:
        result = MODULE.build_result(valid_payload())
        self.assertEqual(result["decision"], MODULE.READY_DECISION)
        self.assertTrue(result["two_consecutive_weekly_shadow_cycles_verified"])
        self.assertTrue(result["immutable_provenance_verified"])
        self.assertTrue(result["replay_noop_verified"])
        self.assertTrue(result["failure_state_observability_verified"])
        self.assertTrue(result["production_canary_plan_ready"])
        self.assertFalse(result["production_canary_authorized"])
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["historical_issue_56_completion_claimed"])

    def test_exact_prior_becomes_noop_and_repeated_noop_stays_noop(self) -> None:
        payload = valid_payload()
        ready = MODULE.build_result(payload)
        first_noop = MODULE.build_result(payload, prior=ready)
        second_noop = MODULE.build_result(payload, prior=first_noop)
        self.assertEqual(first_noop["decision"], MODULE.NO_OP_DECISION)
        self.assertEqual(second_noop["decision"], MODULE.NO_OP_DECISION)
        self.assertEqual(
            ready["acceptance_fingerprint"],
            second_noop["acceptance_fingerprint"],
        )

    def test_gate_c_binding_fail_closed(self) -> None:
        for field, value, message in (
            ("decision", "BLOCKED", "not ready"),
            ("deterministic_replay_verified", False, "replay proof"),
            ("production_eligible", True, "production eligibility"),
            ("weekly_shadow_cycles_complete", True, "pre-claim"),
        ):
            with self.subTest(field=field):
                payload = valid_payload()
                payload["gate_c"][field] = value
                with self.assertRaisesRegex(MODULE.TwoCycleGateError, message):
                    MODULE.build_result(payload)

    def test_legacy_baseline_identity_is_rejected(self) -> None:
        payload = valid_payload()
        payload["gate_c"]["identity"]["gate_b"]["baseline_id"] = "aldi:a31:legacy:reuse"
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "legacy"):
            MODULE.build_result(payload)

    def test_exactly_two_distinct_consecutive_weekly_cycles_are_required(self) -> None:
        payload = valid_payload()
        payload["cycles"] = payload["cycles"][:1]
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "exactly two"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["cycles"][1]["iso_week"] = "2026-W35"
        payload["cycles"][1]["valid_from"] = "2026-08-24"
        payload["cycles"][1]["valid_to"] = "2026-08-29"
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "consecutive"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["cycles"][1]["campaign_id"] = payload["cycles"][0]["campaign_id"]
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "campaigns must be distinct"):
            MODULE.build_result(payload)

    def test_contract_change_restarts_two_cycle_window(self) -> None:
        payload = valid_payload()
        payload["cycles"][1]["parser_identity_sha256"] = "d" * 64
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "parser implementation changed"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["cycles"][1]["parity_contract_sha256"] = "d" * 64
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "parity contract changed"):
            MODULE.build_result(payload)

    def test_replay_must_be_noop_and_immutable(self) -> None:
        fields = (
            ("replay_new_candidate_count", 1, "created new candidates"),
            ("replay_duplicate_candidate_count", 1, "created duplicates"),
            ("immutable_payload_drift_count", 1, "payload drift"),
        )
        for field, value, message in fields:
            with self.subTest(field=field):
                payload = valid_payload()
                payload["cycles"][1][field] = value
                with self.assertRaisesRegex(MODULE.TwoCycleGateError, message):
                    MODULE.build_result(payload)

        payload = valid_payload()
        payload["cycles"][1]["shadow_state_sha256_after_replay"] = "d" * 64
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "shadow state changed"):
            MODULE.build_result(payload)

    def test_review_pending_or_unexplained_cards_block_passing_cycle(self) -> None:
        payload = valid_payload()
        payload["cycles"][1]["review_pending_count"] = 1
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "review-pending"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["cycles"][1]["unexplained_card_count"] = 1
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "unexplained"):
            MODULE.build_result(payload)

    def test_forbidden_writes_and_publication_fail_closed(self) -> None:
        for field in (
            "production_database_write_count",
            "review_write_count",
            "publication_write_count",
            "source_mutation_count",
        ):
            with self.subTest(field=field):
                payload = valid_payload()
                payload["cycles"][1][field] = 1
                with self.assertRaisesRegex(MODULE.TwoCycleGateError, "forbidden write"):
                    MODULE.build_result(payload)

        payload = valid_payload()
        payload["cycles"][1]["production_published"] = True
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "unpublished"):
            MODULE.build_result(payload)

    def test_all_required_observability_states_are_exact(self) -> None:
        payload = valid_payload()
        payload["observability_proofs"] = payload["observability_proofs"][:-1]
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "all required"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["observability_proofs"][0]["observed_decision"] = "BLOCKED"
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "must be observed"):
            MODULE.build_result(payload)

    def test_unsafe_prior_is_rejected(self) -> None:
        payload = valid_payload()
        prior = MODULE.build_result(payload)
        prior["production_canary_authorized"] = True
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "canary authorization"):
            MODULE.build_result(payload, prior=prior)

        prior = MODULE.build_result(payload)
        prior["acceptance_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(MODULE.TwoCycleGateError, "identity differs"):
            MODULE.build_result(payload, prior=prior)

    def test_safety_contract_grants_no_live_authority(self) -> None:
        safety = MODULE.build_result(valid_payload())["safety"]
        self.assertTrue(safety["contract_only"])
        for key, value in safety.items():
            if key == "contract_only":
                continue
            self.assertFalse(value, key)

    def test_cli_output_is_create_only_and_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.json"
            output_path = root / "result.json"
            input_path.write_text(json.dumps(valid_payload()), encoding="utf-8")
            payload = MODULE.load_json(input_path, "two-cycle input")
            result = MODULE.build_result(payload)
            MODULE.write_create_only(output_path, result)
            self.assertEqual(output_path.read_bytes(), MODULE.canonical_bytes(result))
            with self.assertRaisesRegex(MODULE.TwoCycleGateError, "already exists"):
                MODULE.write_create_only(output_path, result)


if __name__ == "__main__":
    unittest.main()
