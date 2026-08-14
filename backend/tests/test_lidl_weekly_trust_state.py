from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "lidl_weekly_trust_state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("lidl_weekly_trust_state", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def one_shot(start: str) -> dict:
    valid_from = date.fromisoformat(start)
    valid_until = valid_from + timedelta(days=5)
    return {
        "result": "READY",
        "reason": "selected_store_source_scan_profile_and_v631_ready",
        "target": "current",
        "today_berlin": start,
        "source": {
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
        },
        "corpus_match": {
            "flyer_key": f"aktionsprospekt-{valid_from:%d-%m-%Y}",
            "scan": "scan-v631-example",
            "source_pdf_sha256": "a" * 64,
            "stable_source_identity_sha256": "b" * 64,
            "parser_input_identity_sha256": "c" * 64,
        },
        "review_profile": {
            "schema_version": 1,
            "status": "reviewed",
            "target_page_count": 23,
        },
        "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
        "parser_sha256": "d" * 64,
        "dry_run": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }


def controller(module, status: dict, *, result: str = "READY") -> dict:
    return {
        "schema_version": 1,
        "controller_version": module.CONTROLLER_VERSION,
        "result": result,
        "execution_fingerprint": module._controller_fingerprint(status),
        "target": status["target"],
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }


def semantic_dir(tmp_path: Path, module, status: dict, *, suffix: str) -> Path:
    root = tmp_path / f"semantic-{suffix}"
    root.mkdir()
    match = status["corpus_match"]
    common = {
        "view_version": module.SEMANTIC_VIEW_VERSION,
        "flyer_key": match["flyer_key"],
        "scan": match["scan"],
        "parser_version": status["parser_version"],
        "parser_sha256": status["parser_sha256"],
        "source_pdf_sha256": match["source_pdf_sha256"],
        "review_profile_sha256": "e" * 64,
        "scan_summary_sha256": "f" * 64,
        "scan_rows_sha256": "1" * 64,
    }
    coverage = {
        **common,
        "production_ready_count": 100,
        "review_required_count": 7,
        "excluded_count": 5,
        "unexplained_count": 0,
        "database_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
    }
    binding = {"schema_version": 1, **common}
    (root / "coverage-report.json").write_text(
        json.dumps(coverage), encoding="utf-8"
    )
    (root / "profile-binding.json").write_text(
        json.dumps(binding), encoding="utf-8"
    )
    (root / "manifest.json").write_text(
        json.dumps({"suffix": suffix}), encoding="utf-8"
    )
    return root


def cycle(tmp_path: Path, module, start: str, *, suffix: str, result: str = "READY"):
    status = one_shot(start)
    return module.build_cycle_evidence(
        controller(module, status, result=result),
        status,
        semantic_dir=semantic_dir(tmp_path, module, status, suffix=suffix),
    )


def test_two_consecutive_scheduled_semantic_cycles_reach_issue_24_gate(
    tmp_path: Path,
) -> None:
    module = load_module()
    first = cycle(tmp_path, module, "2026-08-03", suffix="w32")
    first_state, _ = module.build_state(
        first,
        observed_at=datetime(2026, 8, 8, 18, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    second = cycle(tmp_path, module, "2026-08-10", suffix="w33")
    second_state, receipt = module.build_state(
        second,
        observed_at=datetime(2026, 8, 15, 18, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=first_state,
        previous_state_sha256="2" * 64,
    )

    assert first_state["consecutive_unattended_weekly_cycle_count"] == 1
    assert second_state["consecutive_unattended_weekly_cycle_count"] == 2
    assert second_state[
        "issue_24_two_consecutive_unattended_weekly_cycles_ready"
    ] is True
    assert receipt[
        "issue_24_two_consecutive_unattended_weekly_cycles_ready"
    ] is True
    assert all(
        row["trigger_event"] == "schedule"
        and row["production_write_authorized"] is False
        for row in second_state["scheduled_cycles"]
    )


def test_workflow_dispatch_is_diagnostic_only(tmp_path: Path) -> None:
    module = load_module()
    current = cycle(tmp_path, module, "2026-08-10", suffix="manual")
    state, _ = module.build_state(
        current,
        observed_at=datetime(2026, 8, 14, 8, tzinfo=timezone.utc),
        trigger_event="workflow_dispatch",
        previous=None,
        previous_state_sha256=None,
    )

    assert state["transition_recorded"] is False
    assert state["scheduled_cycles"] == []
    assert state["consecutive_unattended_weekly_cycle_count"] == 0
    assert state["observation"] == "MANUAL_CANARY_NOT_COUNTED"


def test_same_week_exact_no_op_does_not_increment(tmp_path: Path) -> None:
    module = load_module()
    status = one_shot("2026-08-10")
    evidence_root = semantic_dir(tmp_path, module, status, suffix="same")
    first = module.build_cycle_evidence(
        controller(module, status, result="READY"),
        status,
        semantic_dir=evidence_root,
    )
    first_state, _ = module.build_state(
        first,
        observed_at=datetime(2026, 8, 14, 7, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    replay = module.build_cycle_evidence(
        controller(module, status, result="NO_OP"),
        status,
        semantic_dir=evidence_root,
    )
    replay_state, _ = module.build_state(
        replay,
        observed_at=datetime(2026, 8, 14, 8, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=first_state,
        previous_state_sha256="3" * 64,
    )

    assert replay_state["transition_recorded"] is False
    assert replay_state["semantic_no_op"] is True
    assert replay_state["observation"] == "UNCHANGED_SEMANTIC_NO_OP"
    assert replay_state["consecutive_unattended_weekly_cycle_count"] == 1


def test_same_week_conflicting_completed_identity_fails_closed(tmp_path: Path) -> None:
    module = load_module()
    first = cycle(tmp_path, module, "2026-08-10", suffix="a")
    first_state, _ = module.build_state(
        first,
        observed_at=datetime(2026, 8, 14, 7, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    conflict = cycle(tmp_path, module, "2026-08-10", suffix="b")

    with pytest.raises(
        module.LidlWeeklyTrustStateError,
        match="same ISO week has conflicting completed cycle identity",
    ):
        module.build_state(
            conflict,
            observed_at=datetime(2026, 8, 14, 8, tzinfo=timezone.utc),
            trigger_event="schedule",
            previous=first_state,
            previous_state_sha256="4" * 64,
        )


def test_gap_week_breaks_consecutive_chain(tmp_path: Path) -> None:
    module = load_module()
    first = cycle(tmp_path, module, "2026-08-03", suffix="w32")
    first_state, _ = module.build_state(
        first,
        observed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    third = cycle(tmp_path, module, "2026-08-17", suffix="w34")
    third_state, _ = module.build_state(
        third,
        observed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=first_state,
        previous_state_sha256="5" * 64,
    )

    assert third_state["consecutive_unattended_weekly_cycle_count"] == 1
    assert third_state[
        "issue_24_two_consecutive_unattended_weekly_cycles_ready"
    ] is False


@pytest.mark.parametrize("controller_result", ["WAIT", "BLOCKED"])
def test_non_completed_controller_state_cannot_be_cycle_evidence(
    tmp_path: Path, controller_result: str
) -> None:
    module = load_module()
    status = one_shot("2026-08-10")
    manifest = controller(module, status)
    manifest["result"] = controller_result

    with pytest.raises(
        module.LidlWeeklyTrustStateError,
        match="controller is not a completed shadow decision",
    ):
        module.build_cycle_evidence(
            manifest,
            status,
            semantic_dir=semantic_dir(
                tmp_path, module, status, suffix=controller_result
            ),
        )


def test_semantic_safety_mismatch_fails_closed(tmp_path: Path) -> None:
    module = load_module()
    status = one_shot("2026-08-10")
    root = semantic_dir(tmp_path, module, status, suffix="unsafe")
    coverage_path = root / "coverage-report.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["auto_publish"] = True
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    with pytest.raises(
        module.LidlWeeklyTrustStateError,
        match="semantic safety mismatch: auto_publish",
    ):
        module.build_cycle_evidence(
            controller(module, status),
            status,
            semantic_dir=root,
        )


def test_previous_state_rejects_manual_cycle_in_persisted_history() -> None:
    module = load_module()
    bad = {
        "schema_version": 1,
        "strategy": module.STRATEGY,
        "production_write_authorized": False,
        "scheduled_cycles": [
            {
                "iso_week": "2026-W33",
                "week_start": "2026-08-10",
                "cycle_identity_sha256": "a" * 64,
                "trigger_event": "workflow_dispatch",
                "production_write_authorized": False,
                "recorded_at": "2026-08-14T08:00:00+00:00",
            }
        ],
    }

    with pytest.raises(
        module.LidlWeeklyTrustStateError,
        match="persisted cycle must come from schedule",
    ):
        module.validate_previous(bad)
