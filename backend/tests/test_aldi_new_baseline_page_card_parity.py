from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "aldi_new_baseline_page_card_parity.py"
SPEC = importlib.util.spec_from_file_location(
    "aldi_new_baseline_page_card_parity",
    TOOL_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def candidate(
    candidate_id: str,
    *,
    page: int,
    card_id: str,
    route: str = "auto_candidate",
    reason: str = "",
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "payload_sha256": f"{page:064x}",
        "page_number": page,
        "card_id": card_id,
        "route": route,
        "reason": reason,
    }


def card(
    card_id: str,
    *,
    page: int,
    candidate_ids: list[str],
    scope: str = "in_scope",
    route: str = "candidate",
    reason: str = "",
) -> dict[str, object]:
    return {
        "card_id": card_id,
        "page_number": page,
        "page_sha256": f"{page + 100:064x}",
        "region": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.2},
        "scope": scope,
        "route": route,
        "candidate_ids": candidate_ids,
        "reason": reason,
    }


def valid_payload() -> dict[str, object]:
    candidates = [
        candidate("cand-001", page=1, card_id="p001:c001"),
        candidate(
            "cand-002",
            page=2,
            card_id="p002:c001",
            route="review_required",
            reason="ambiguous package ownership",
        ),
    ]
    cards = [
        card("p001:c001", page=1, candidate_ids=["cand-001"]),
        card(
            "p002:c001",
            page=2,
            candidate_ids=["cand-002"],
            scope="review",
            route="review",
            reason="ambiguous package ownership",
        ),
        card(
            "p003:c001",
            page=3,
            candidate_ids=[],
            scope="excluded",
            route="excluded",
            reason="non-food card outside target scope",
        ),
    ]
    return {
        "schema_version": 1,
        "mode": MODULE.MODE,
        "issue_number": 682,
        "baseline": {
            "gate_a_mode": MODULE.GATE_A_MODE,
            "gate_a_decision": MODULE.GATE_A_DECISION,
            "baseline_id": "aldi-nord:2026-cw33:region-0:v1",
            "baseline_fingerprint": "a" * 64,
            "page_manifest_sha256": "b" * 64,
            "page_count": 41,
            "historical_issue_56_completion_claimed": False,
        },
        "candidate_projection": {
            "projection_sha256": MODULE.canonical_sha256(
                sorted(candidates, key=lambda row: row["candidate_id"])
            ),
            "candidates": candidates,
        },
        "card_ledger": {
            "ledger_sha256": MODULE.canonical_sha256(
                sorted(cards, key=lambda row: row["card_id"])
            ),
            "cards": cards,
        },
    }


class AldiNewBaselinePageCardParityTest(unittest.TestCase):
    def test_valid_explicit_bidirectional_ledger_reaches_gate_c(self) -> None:
        result = MODULE.validate_parity(valid_payload())
        self.assertEqual(result["decision"], "READY_FOR_NEW_BASELINE_GATE_C")
        self.assertTrue(result["parity_complete"])
        self.assertTrue(result["gate_c_continuation_ready"])
        self.assertEqual(result["summary"]["unexplained_card_count"], 0)
        self.assertEqual(result["summary"]["auto_candidate_count"], 1)
        self.assertEqual(result["summary"]["review_candidate_count"], 1)
        self.assertEqual(result["summary"]["excluded_card_count"], 1)
        self.assertFalse(result["historical_issue_56_completion_claimed"])
        self.assertFalse(result["production_eligible"])

    def test_historical_or_gate_a_identity_drift_fails_closed(self) -> None:
        payload = valid_payload()
        payload["baseline"]["historical_issue_56_completion_claimed"] = True
        with self.assertRaisesRegex(MODULE.ParityGateError, "completion"):
            MODULE.validate_parity(payload)

        payload = valid_payload()
        payload["baseline"]["gate_a_decision"] = "PASS"
        with self.assertRaisesRegex(MODULE.ParityGateError, "decision"):
            MODULE.validate_parity(payload)

        payload = valid_payload()
        payload["baseline"]["baseline_id"] = "aldi:a31:legacy:reuse"
        with self.assertRaisesRegex(MODULE.ParityGateError, "legacy"):
            MODULE.validate_parity(payload)

    def test_candidate_card_binding_is_bidirectional_and_page_exact(self) -> None:
        payload = valid_payload()
        payload["card_ledger"]["cards"][0]["candidate_ids"] = []
        payload["card_ledger"]["ledger_sha256"] = MODULE.canonical_sha256(
            sorted(payload["card_ledger"]["cards"], key=lambda row: row["card_id"])
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "requires candidate binding"):
            MODULE.validate_parity(payload)

        payload = valid_payload()
        payload["candidate_projection"]["candidates"][0]["page_number"] = 2
        payload["candidate_projection"]["projection_sha256"] = MODULE.canonical_sha256(
            sorted(
                payload["candidate_projection"]["candidates"],
                key=lambda row: row["candidate_id"],
            )
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "page/card mismatch"):
            MODULE.validate_parity(payload)

    def test_review_and_excluded_routes_require_explicit_reason(self) -> None:
        payload = valid_payload()
        payload["candidate_projection"]["candidates"][1]["reason"] = ""
        payload["candidate_projection"]["projection_sha256"] = MODULE.canonical_sha256(
            sorted(
                payload["candidate_projection"]["candidates"],
                key=lambda row: row["candidate_id"],
            )
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "requires reason"):
            MODULE.validate_parity(payload)

        payload = valid_payload()
        payload["card_ledger"]["cards"][2]["reason"] = ""
        payload["card_ledger"]["ledger_sha256"] = MODULE.canonical_sha256(
            sorted(payload["card_ledger"]["cards"], key=lambda row: row["card_id"])
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "requires reason"):
            MODULE.validate_parity(payload)

    def test_route_conflict_cannot_promote_review_or_excluded_to_candidate(self) -> None:
        payload = valid_payload()
        payload["candidate_projection"]["candidates"][1]["route"] = "auto_candidate"
        payload["candidate_projection"]["candidates"][1]["reason"] = ""
        payload["candidate_projection"]["projection_sha256"] = MODULE.canonical_sha256(
            sorted(
                payload["candidate_projection"]["candidates"],
                key=lambda row: row["candidate_id"],
            )
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "conflicts with card route"):
            MODULE.validate_parity(payload)

    def test_unknown_candidate_or_card_reference_fails_closed(self) -> None:
        payload = valid_payload()
        payload["candidate_projection"]["candidates"][0]["card_id"] = "p001:c999"
        payload["candidate_projection"]["projection_sha256"] = MODULE.canonical_sha256(
            sorted(
                payload["candidate_projection"]["candidates"],
                key=lambda row: row["candidate_id"],
            )
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "unknown card"):
            MODULE.validate_parity(payload)

        payload = valid_payload()
        payload["card_ledger"]["cards"][0]["candidate_ids"] = ["missing-candidate"]
        payload["card_ledger"]["ledger_sha256"] = MODULE.canonical_sha256(
            sorted(payload["card_ledger"]["cards"], key=lambda row: row["card_id"])
        )
        with self.assertRaisesRegex(MODULE.ParityGateError, "reverse candidate binding mismatch"):
            MODULE.validate_parity(payload)

    def test_fingerprints_are_order_independent(self) -> None:
        payload = valid_payload()
        first = MODULE.validate_parity(payload)

        reversed_payload = valid_payload()
        reversed_payload["candidate_projection"]["candidates"].reverse()
        reversed_payload["card_ledger"]["cards"].reverse()
        second = MODULE.validate_parity(reversed_payload)

        self.assertEqual(first["parity_fingerprint"], second["parity_fingerprint"])
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(first["cards"], second["cards"])

    def test_input_hashes_are_enforced(self) -> None:
        payload = valid_payload()
        payload["candidate_projection"]["projection_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.ParityGateError, "projection SHA256"):
            MODULE.validate_parity(payload)

        payload = valid_payload()
        payload["card_ledger"]["ledger_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.ParityGateError, "ledger SHA256"):
            MODULE.validate_parity(payload)

    def test_safety_contract_grants_no_live_authority(self) -> None:
        result = MODULE.validate_parity(valid_payload())
        safety = result["safety"]
        self.assertTrue(safety["contract_only"])
        for key, value in safety.items():
            if key == "contract_only":
                continue
            self.assertFalse(value, key)

    def test_cli_output_is_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.json"
            output_path = root / "result.json"
            input_path.write_text(json.dumps(valid_payload()), encoding="utf-8")
            result = MODULE.validate_parity(MODULE.load_input(input_path))
            MODULE.write_create_only(output_path, result)
            self.assertEqual(output_path.read_bytes(), MODULE.canonical_bytes(result))
            with self.assertRaisesRegex(MODULE.ParityGateError, "already exists"):
                MODULE.write_create_only(output_path, result)


if __name__ == "__main__":
    unittest.main()
