from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "lidl_v631_canary.py"
SPEC = importlib.util.spec_from_file_location("lidl_v631_canary_tool", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _Scalar:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _PlanDb:
    def __init__(self) -> None:
        self.calls = 0
        self.rolled_back = False

    def execute(self, statement):
        text = str(statement)
        if text.startswith("SET TRANSACTION"):
            return _Scalar("")
        if "transaction_read_only" in text:
            return _Scalar("on")
        if "transaction_isolation" in text:
            return _Scalar("repeatable read")
        raise AssertionError(text)

    def rollback(self) -> None:
        self.rolled_back = True


def _plan() -> dict[str, object]:
    return {
        "result": "READY_TO_CREATE",
        "payload_fingerprint": "a" * 64,
        "plan_fingerprint": "b" * 64,
        "bindings": {
            "reviewed_canary_receipt_sha256": "c" * 64,
            "semantic_row_key": "d" * 64,
        },
        "source_snapshot": {"id": "11111111-1111-1111-1111-111111111111"},
        "offer_candidate": {
            "id": "22222222-2222-2222-2222-222222222222",
            "source_offer_id": "lidl:v631:family:" + "d" * 64,
        },
        "expected_deltas": {
            "first_apply": {"source_snapshots": 1, "offer_candidates": 1},
            "replay": {"source_snapshots": 0, "offer_candidates": 0},
        },
    }


def test_plan_is_one_readonly_operator_step_with_exact_authorization_payload() -> None:
    db = _PlanDb()
    with (
        patch.object(MODULE, "_counts", side_effect=[{"source_snapshots": 10, "offer_candidates": 20}, {"source_snapshots": 10, "offer_candidates": 20}]),
        patch.object(MODULE, "build_lidl_v631_semantic_persistence_plan", return_value=_plan()),
    ):
        report = MODULE.run_plan(db, receipt_raw=b"receipt", row={"x": 1}, source_binding={"x": 1})

    assert db.rolled_back is True
    assert report["result"] == "PLAN_PASS"
    assert report["plan_result"] == "READY_TO_CREATE"
    assert report["transaction_read_only"] == "on"
    assert report["transaction_isolation"] == "repeatable read"
    assert report["expected_first_apply_delta"] == {"source_snapshots": 1, "offer_candidates": 1}
    assert report["production_database_write"] is False
    assert report["authorization"]["plan_fingerprint"] == "b" * 64
    assert report["authorization"]["permissions"]["max_source_snapshot_writes"] == 1
    assert report["authorization"]["permissions"]["max_offer_candidate_writes"] == 1


def test_plan_fails_closed_on_conflict() -> None:
    db = _PlanDb()
    blocked = _plan()
    blocked["result"] = "BLOCKED_CONFLICT"
    with (
        patch.object(MODULE, "_counts", side_effect=[{"source_snapshots": 10, "offer_candidates": 20}, {"source_snapshots": 10, "offer_candidates": 20}]),
        patch.object(MODULE, "build_lidl_v631_semantic_persistence_plan", return_value=blocked),
    ):
        try:
            MODULE.run_plan(db, receipt_raw=b"receipt", row={"x": 1}, source_binding={"x": 1})
        except MODULE.LidlC3ReadonlyPreflightError:
            pass
        else:
            raise AssertionError("blocked plan was accepted")


def test_cli_has_only_plan_and_apply_operator_modes() -> None:
    parser = MODULE._parser()
    mode = next(action for action in parser._actions if action.dest == "mode")
    assert tuple(mode.choices) == ("plan", "apply")
