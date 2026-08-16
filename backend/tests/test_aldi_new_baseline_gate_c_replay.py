from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "aldi_new_baseline_gate_c_replay.py"
SPEC = importlib.util.spec_from_file_location("aldi_new_baseline_gate_c_replay", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_payload() -> dict[str, object]:
    gate_b = {
        "mode": MODULE.GATE_B_MODE,
        "decision": MODULE.GATE_B_DECISION,
        "baseline_id": "aldi-nord:2026-cw33:region-0:v1",
        "baseline_fingerprint": "a" * 64,
        "parity_fingerprint": "b" * 64,
        "candidate_projection_sha256": "c" * 64,
        "card_ledger_sha256": "d" * 64,
        "candidate_count": 42,
        "card_count": 50,
        "unexplained_card_count": 0,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
    }
    input_sha = MODULE.expected_replay_input_sha256(gate_b)
    replays = [
        {
            "replay_id": f"replay-{index:02d}",
            "execution_class": "offline_shadow_replay",
            "input_identity_sha256": input_sha,
            "semantic_output_sha256": "e" * 64,
            "candidate_projection_sha256": gate_b["candidate_projection_sha256"],
            "card_ledger_sha256": gate_b["card_ledger_sha256"],
            "candidate_count": gate_b["candidate_count"],
            "card_count": gate_b["card_count"],
            "unexplained_card_count": 0,
            "duplicate_candidate_count": 0,
            "state_write_count": 0,
            "candidate_write_count": 0,
            "review_write_count": 0,
            "database_write_count": 0,
        }
        for index in (1, 2)
    ]
    return {
        "schema_version": 1,
        "mode": MODULE.MODE,
        "issue_number": 682,
        "gate_b": gate_b,
        "replays": replays,
    }


class AldiNewBaselineGateCReplayTest(unittest.TestCase):
    def test_valid_replay_reaches_weekly_shadow_cycle_boundary(self) -> None:
        result = MODULE.build_result(valid_payload())
        self.assertEqual(result["decision"], MODULE.READY_DECISION)
        self.assertTrue(result["deterministic_replay_verified"])
        self.assertTrue(result["duplicate_free_verified"])
        self.assertTrue(result["idempotency_verified"])
        self.assertTrue(result["second_replay_no_mutation_verified"])
        self.assertFalse(result["weekly_shadow_cycles_complete"])
        self.assertFalse(result["production_eligible"])
        self.assertFalse(result["historical_issue_56_completion_claimed"])
        self.assertEqual(result["next_gate"]["required_cycle_count"], 2)

    def test_exact_prior_becomes_no_op_and_repeated_no_op_stays_no_op(self) -> None:
        payload = valid_payload()
        ready = MODULE.build_result(payload)
        first_no_op = MODULE.build_result(payload, prior=ready)
        repeated_no_op = MODULE.build_result(payload, prior=first_no_op)

        self.assertEqual(first_no_op["decision"], MODULE.NO_OP_DECISION)
        self.assertEqual(repeated_no_op["decision"], MODULE.NO_OP_DECISION)
        self.assertEqual(
            ready["replay_identity_sha256"],
            repeated_no_op["replay_identity_sha256"],
        )

    def test_gate_b_identity_and_historical_boundaries_fail_closed(self) -> None:
        payload = valid_payload()
        payload["gate_b"]["parity_fingerprint"] = "f" * 64
        with self.assertRaisesRegex(MODULE.GateCError, "input identity drift"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["gate_b"]["historical_issue_56_completion_claimed"] = True
        with self.assertRaisesRegex(MODULE.GateCError, "historical issue #56"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["gate_b"]["baseline_id"] = "aldi:a31:legacy:reuse"
        with self.assertRaisesRegex(MODULE.GateCError, "legacy"):
            MODULE.build_result(payload)

    def test_replay_semantic_or_projection_drift_fails_closed(self) -> None:
        payload = valid_payload()
        payload["replays"][1]["semantic_output_sha256"] = "f" * 64
        with self.assertRaisesRegex(MODULE.GateCError, "semantic output drift"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["replays"][1]["candidate_projection_sha256"] = "f" * 64
        with self.assertRaisesRegex(MODULE.GateCError, "candidate projection drift"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["replays"][1]["card_ledger_sha256"] = "f" * 64
        with self.assertRaisesRegex(MODULE.GateCError, "card ledger drift"):
            MODULE.build_result(payload)

    def test_duplicate_or_unexplained_cards_fail_closed(self) -> None:
        payload = valid_payload()
        payload["replays"][1]["duplicate_candidate_count"] = 1
        with self.assertRaisesRegex(MODULE.GateCError, "duplicate candidates"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["replays"][1]["unexplained_card_count"] = 1
        with self.assertRaisesRegex(MODULE.GateCError, "unexplained cards"):
            MODULE.build_result(payload)

    def test_any_replay_write_fails_closed(self) -> None:
        for field in (
            "state_write_count",
            "candidate_write_count",
            "review_write_count",
            "database_write_count",
        ):
            with self.subTest(field=field):
                payload = valid_payload()
                payload["replays"][1][field] = 1
                with self.assertRaisesRegex(MODULE.GateCError, "read-only"):
                    MODULE.build_result(payload)

    def test_two_exact_ordered_replays_are_required(self) -> None:
        payload = valid_payload()
        payload["replays"] = payload["replays"][:1]
        with self.assertRaisesRegex(MODULE.GateCError, "exactly two"):
            MODULE.build_result(payload)

        payload = valid_payload()
        payload["replays"][0]["replay_id"] = "replay-02"
        with self.assertRaisesRegex(MODULE.GateCError, "ordered"):
            MODULE.build_result(payload)

    def test_unsafe_or_drifted_prior_is_rejected(self) -> None:
        payload = valid_payload()
        prior = MODULE.build_result(payload)
        prior["production_eligible"] = True
        with self.assertRaisesRegex(MODULE.GateCError, "production eligibility"):
            MODULE.build_result(payload, prior=prior)

        prior = MODULE.build_result(payload)
        prior["replay_identity_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.GateCError, "identity differs"):
            MODULE.build_result(payload, prior=prior)

        prior = MODULE.build_result(payload)
        prior["weekly_shadow_cycles_complete"] = True
        with self.assertRaisesRegex(MODULE.GateCError, "weekly shadow completion"):
            MODULE.build_result(payload, prior=prior)

    def test_safety_contract_grants_no_live_authority(self) -> None:
        result = MODULE.build_result(valid_payload())
        safety = result["safety"]
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

            payload = MODULE.load_json(input_path, "Gate C input")
            result = MODULE.build_result(payload)
            MODULE.write_create_only(output_path, result)

            self.assertEqual(output_path.read_bytes(), MODULE.canonical_bytes(result))
            with self.assertRaisesRegex(MODULE.GateCError, "already exists"):
                MODULE.write_create_only(output_path, result)


if __name__ == "__main__":
    unittest.main()
