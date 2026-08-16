from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "aldi_new_baseline_weekly_shadow_bridge.py"
SPEC = importlib.util.spec_from_file_location("aldi_new_baseline_weekly_shadow_bridge", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def gate_a_result() -> dict[str, object]:
    return {
        "mode": "ALDI_NEW_IMMUTABLE_BASELINE_GATE_A_V01",
        "decision": "READY_FOR_NEW_BASELINE_ADJUDICATION",
        "baseline_fingerprint": "1" * 64,
        "baseline_identity": {
            "baseline_id": "aldi-nord:2026-cw33:region-0:v2",
            "campaign": {
                "campaign_id": "aldi-nord-2026-w33-region-0-v2",
                "valid_from": "2026-08-10",
                "valid_until": "2026-08-15",
            },
            "sources": [
                {
                    "source_id": "weekly",
                    "url": "https://www.aldi-nord.de/angebote/aktion-mo-10-08.html",
                    "sha256": "2" * 64,
                }
            ],
            "parser_identity": {
                "implementation_sha256": "a" * 64,
            },
        },
        "page_manifest": {
            "manifest_sha256": "3" * 64,
            "page_count": 41,
        },
    }


def gate_b_result() -> dict[str, object]:
    return {
        "mode": "ALDI_NEW_BASELINE_PAGE_CARD_PARITY_V01",
        "decision": "READY_FOR_NEW_BASELINE_GATE_C",
        "parity_fingerprint": "4" * 64,
        "baseline": {
            "baseline_id": "aldi-nord:2026-cw33:region-0:v2",
            "baseline_fingerprint": "1" * 64,
        },
        "candidate_projection": {"projection_sha256": "5" * 64},
        "card_ledger": {"ledger_sha256": "6" * 64},
        "summary": {
            "candidate_count": 321,
            "card_count": 351,
            "review_candidate_count": 21,
            "excluded_card_count": 10,
            "unexplained_card_count": 0,
        },
    }


def gate_c_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "ALDI_NEW_BASELINE_GATE_C_REPLAY_V01",
        "issue_number": 682,
        "decision": "READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES",
        "replay_identity_sha256": "7" * 64,
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
                "baseline_id": "aldi-nord:2026-cw33:region-0:v2",
                "baseline_fingerprint": "1" * 64,
            },
            "semantic_output_sha256": "8" * 64,
        },
    }


def request_payload(main_sha: str, descriptors: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": MODULE.REQUEST_MODE,
        "issue_number": 682,
        "retailer": "ALDI Nord",
        "owner_login": "rozkalnsandris",
        "owner_id": 277435981,
        "authorized_main_sha": main_sha,
        "automatic_schedule": False,
        "production_deploy_authorized": False,
        "production_canary_authorized": False,
        "production_database_write_authorized": False,
        "review_or_publication_write_authorized": False,
        "source_mutation_authorized": False,
        "files": descriptors,
    }


def execution_evidence() -> dict[str, object]:
    return {
        "schema_version": 1,
        "evidence_class": "real_weekly_shadow",
        "execution_origin": "rpi5_shadow",
        "source_state": "available",
        "primary_source_id": "weekly",
        "observed_at_utc": "2026-08-10T08:15:00Z",
        "iso_week": "2026-W33",
        "review_pending_count": 0,
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


class AldiNewBaselineWeeklyShadowBridgeTest(unittest.TestCase):
    def make_request_dir(
        self,
        root: Path,
        *,
        main_sha: str = "d" * 40,
        include_prior: bool = False,
    ) -> tuple[Path, str]:
        request_dir = root / "request"
        request_dir.mkdir()
        payloads = {
            "gate_a_input": {"placeholder": "a"},
            "gate_b_input": {"baseline": MODULE.expected_gate_b_binding(gate_a_result())},
            "gate_c_input": {"gate_b": MODULE.expected_gate_c_binding(gate_b_result())},
            "execution_evidence": execution_evidence(),
        }
        if include_prior:
            payloads["prior_cycle"] = {"cycle_id": "cycle-current"}
            payloads["observability_proofs"] = {
                "schema_version": 1,
                "observability_proofs": [],
            }

        descriptors: dict[str, object] = {}
        names = dict(MODULE.FIXED_FILES)
        if include_prior:
            names.update(MODULE.OPTIONAL_FILES)
        for key, name in names.items():
            data = MODULE.canonical_bytes(payloads[key])
            (request_dir / name).write_bytes(data)
            descriptors[key] = {"path": name, "sha256": sha(data)}

        request = request_payload(main_sha, descriptors)
        request_bytes = MODULE.canonical_bytes(request)
        (request_dir / "request.json").write_bytes(request_bytes)
        return request_dir, sha(request_bytes)

    def test_request_is_exactly_bound_to_main_and_file_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request_dir, request_sha = self.make_request_dir(Path(tmp))
            request, resolved = MODULE.validate_request(
                request_dir,
                request_sha256=request_sha,
                expected_main_sha="d" * 40,
                authorization_comment_id=1234,
                github_run_id=5678,
            )
            self.assertEqual(request["issue_number"], 682)
            self.assertEqual(set(resolved), set(MODULE.FIXED_FILES))

            with self.assertRaisesRegex(MODULE.BridgeError, "main SHA drift"):
                MODULE.validate_request(
                    request_dir,
                    request_sha256=request_sha,
                    expected_main_sha="e" * 40,
                    authorization_comment_id=1234,
                    github_run_id=5678,
                )

            gate_a_path = request_dir / MODULE.FIXED_FILES["gate_a_input"]
            gate_a_path.write_text('{"drift":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(MODULE.BridgeError, "SHA256 mismatch"):
                MODULE.validate_request(
                    request_dir,
                    request_sha256=request_sha,
                    expected_main_sha="d" * 40,
                    authorization_comment_id=1234,
                    github_run_id=5678,
                )

    def test_optional_two_cycle_inputs_are_all_or_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request_dir, _ = self.make_request_dir(Path(tmp), include_prior=True)
            request = json.loads((request_dir / "request.json").read_text())
            del request["files"]["observability_proofs"]
            request_bytes = MODULE.canonical_bytes(request)
            (request_dir / "request.json").write_bytes(request_bytes)
            with self.assertRaisesRegex(MODULE.BridgeError, "supplied together"):
                MODULE.validate_request(
                    request_dir,
                    request_sha256=sha(request_bytes),
                    expected_main_sha="d" * 40,
                    authorization_comment_id=1234,
                    github_run_id=5678,
                )

    def test_gate_chain_requires_exact_cross_bindings(self) -> None:
        a = gate_a_result()
        b = gate_b_result()
        self.assertEqual(
            MODULE.expected_gate_b_binding(a)["baseline_fingerprint"],
            "1" * 64,
        )
        self.assertEqual(
            MODULE.expected_gate_c_binding(b)["parity_fingerprint"],
            "4" * 64,
        )

    def test_execution_evidence_is_read_only_and_bound_to_gate_a_source(self) -> None:
        evidence = MODULE.validate_execution_evidence(
            execution_evidence(),
            gate_a=gate_a_result(),
            gate_b=gate_b_result(),
            github_run_id=9001,
        )
        self.assertEqual(evidence["run_id"], 9001)
        self.assertEqual(evidence["source_sha256"], "2" * 64)
        self.assertEqual(evidence["production_database_write_count"], 0)

        unsafe = execution_evidence()
        unsafe["review_write_count"] = 1
        with self.assertRaisesRegex(MODULE.BridgeError, "review_write_count must be zero"):
            MODULE.validate_execution_evidence(
                unsafe,
                gate_a=gate_a_result(),
                gate_b=gate_b_result(),
                github_run_id=9001,
            )

        drift = execution_evidence()
        drift["shadow_state_sha256_after_replay"] = "d" * 64
        with self.assertRaisesRegex(MODULE.BridgeError, "shadow state changed"):
            MODULE.validate_execution_evidence(
                drift,
                gate_a=gate_a_result(),
                gate_b=gate_b_result(),
                github_run_id=9001,
            )

    def test_one_week_bridge_accepts_only_after_gate_a_b_c(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request_dir, request_sha = self.make_request_dir(Path(tmp))
            parity_contract_sha = MODULE.file_sha256(Path(MODULE.gate_b_module.__file__))
            with (
                mock.patch.object(MODULE.gate_a_module, "validate_baseline", return_value=gate_a_result()),
                mock.patch.object(MODULE.gate_b_module, "validate_parity", return_value=gate_b_result()),
                mock.patch.object(MODULE.gate_c_module, "build_result", return_value=gate_c_result()),
            ):
                result = MODULE.run_bridge(
                    request_dir=request_dir,
                    request_sha256=request_sha,
                    expected_main_sha="d" * 40,
                    authorization_comment_id=1234,
                    github_run_id=9001,
                )
            self.assertEqual(result["decision"], MODULE.FIRST_WEEK_DECISION)
            self.assertFalse(result["production_canary_plan_ready"])
            self.assertFalse(result["production_canary_authorized"])
            self.assertFalse(result["production_deploy_authorized"])
            self.assertFalse(result["historical_issue_56_completion_claimed"])
            self.assertEqual(result["current_cycle"]["cycle_id"], "cycle-current")
            self.assertEqual(result["current_cycle"]["parity_contract_sha256"], parity_contract_sha)

    def test_gate_b_or_c_identity_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request_dir, request_sha = self.make_request_dir(Path(tmp))
            bad_b = gate_b_result()
            bad_b["parity_fingerprint"] = "9" * 64
            with mock.patch.object(MODULE.gate_a_module, "validate_baseline", return_value=gate_a_result()):
                bad_input = json.loads((request_dir / "gate-b-input.json").read_text())
                bad_input["baseline"]["baseline_fingerprint"] = "9" * 64
                (request_dir / "gate-b-input.json").write_bytes(MODULE.canonical_bytes(bad_input))
                # Update request descriptor so the hash itself is valid; cross-binding must still reject.
                request = json.loads((request_dir / "request.json").read_text())
                new_hash = MODULE.file_sha256(request_dir / "gate-b-input.json")
                request["files"]["gate_b_input"]["sha256"] = new_hash
                request_bytes = MODULE.canonical_bytes(request)
                (request_dir / "request.json").write_bytes(request_bytes)
                with self.assertRaisesRegex(MODULE.BridgeError, "not exactly bound"):
                    MODULE.run_bridge(
                        request_dir=request_dir,
                        request_sha256=sha(request_bytes),
                        expected_main_sha="d" * 40,
                        authorization_comment_id=1234,
                        github_run_id=9001,
                    )

    def test_output_is_create_only_and_manifested(self) -> None:
        result = {
            "gate_a": {"a": 1},
            "gate_b": {"b": 2},
            "gate_c": {"c": 3},
            "current_cycle": {"cycle": 1},
            "two_cycle_result": None,
            "decision": MODULE.FIRST_WEEK_DECISION,
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            MODULE.write_outputs(out, result)
            self.assertTrue((out / "MANIFEST.sha256").is_file())
            self.assertTrue((out / "sanitized-result.json").is_file())
            with self.assertRaisesRegex(MODULE.BridgeError, "already exists"):
                MODULE.write_outputs(out, result)


if __name__ == "__main__":
    unittest.main()
