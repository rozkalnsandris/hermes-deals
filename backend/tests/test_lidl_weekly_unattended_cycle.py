from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "lidl_weekly_unattended_cycle.py"


def load_module():
    spec = importlib.util.spec_from_file_location("lidl_weekly_unattended_cycle", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_digest(value: dict) -> str:
    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_corpus(tmp_path: Path) -> tuple[Path, str, str]:
    corpus = tmp_path / "corpus"
    flyer_key = "aktionsprospekt-10-08-2026-15-08-2026-example"
    scan = "scan-v631-example"
    (corpus / "flyers" / flyer_key / "scans" / scan).mkdir(parents=True)
    return corpus, flyer_key, scan


def one_shot(flyer_key: str, scan: str) -> dict:
    return {
        "result": "READY",
        "target": "current",
        "source": {
            "valid_from": "2026-08-10",
            "valid_until": "2026-08-15",
            "readiness": {"page_count": 69},
        },
        "corpus_match": {
            "flyer_key": flyer_key,
            "scan": scan,
        },
    }


def previous_bundle(tmp_path: Path, module, *, tamper_receipt: bool = False) -> Path:
    root = tmp_path / "previous"
    controller = root / "controller"
    controller.mkdir(parents=True)
    (controller / "controller-manifest.json").write_text("{}\n", encoding="utf-8")
    state = {
        "schema_version": 1,
        "strategy": module.TRUST_STATE_STRATEGY,
        "production_write_authorized": False,
        "scheduled_cycles": [],
    }
    state_path = root / "trust-state.json"
    module.write_create_only(state_path, state)
    receipt = {
        "schema_version": 1,
        "strategy": module.RECEIPT_STRATEGY,
        "state_sha256": ("f" * 64 if tamper_receipt else module.sha_file(state_path)),
    }
    module.write_create_only(root / "trust-receipt.json", receipt)
    return root


def patch_completed_cycle(
    monkeypatch,
    module,
    *,
    status: dict,
    controller_result: str,
    semantic_no_op: bool,
    transition_recorded: bool,
    observation: str,
) -> None:
    def fake_run_controller(**kwargs):
        output = kwargs["output_dir"]
        one_shot_dir = output / "one-shot"
        one_shot_dir.mkdir(parents=True)
        (one_shot_dir / "one-shot-status.json").write_text(
            json.dumps(status),
            encoding="utf-8",
        )
        return {
            "result": controller_result,
            "reason": (
                "unchanged_exact_shadow_input"
                if controller_result == module.NO_OP_STATE
                else "new_exact_shadow_input"
            ),
        }

    def fake_semantic_view(**kwargs):
        output = kwargs["output_dir"]
        output.mkdir(parents=True)
        (output / "sentinel").write_text("read-only semantic evidence", encoding="utf-8")
        return {"result": "SEMANTIC_VIEW_READY"}

    def fake_cycle_evidence(controller, current_status, *, semantic_dir):
        assert controller["result"] == controller_result
        assert current_status == status
        assert (semantic_dir / "sentinel").is_file()
        return {"strategy": "lidl_weekly_shadow_cycle_evidence_v1"}

    state = {
        "schema_version": 1,
        "strategy": module.TRUST_STATE_STRATEGY,
        "observation": observation,
        "semantic_no_op": semantic_no_op,
        "transition_recorded": transition_recorded,
        "consecutive_unattended_weekly_cycle_count": 1,
        "issue_24_two_consecutive_unattended_weekly_cycles_ready": False,
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "systemd_change_performed": False,
        "scheduled_cycles": [],
    }
    receipt = {
        "schema_version": 1,
        "strategy": module.RECEIPT_STRATEGY,
        "state_sha256": canonical_digest(state),
    }

    monkeypatch.setattr(module, "run_controller", fake_run_controller)
    monkeypatch.setattr(module, "build_semantic_view", fake_semantic_view)
    monkeypatch.setattr(module, "build_cycle_evidence", fake_cycle_evidence)
    monkeypatch.setattr(module, "build_state", lambda *args, **kwargs: (state, receipt))


def test_ready_schedule_composes_read_only_cycle(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    corpus, flyer_key, scan = make_corpus(tmp_path)
    status = one_shot(flyer_key, scan)
    patch_completed_cycle(
        monkeypatch,
        module,
        status=status,
        controller_result=module.READY_STATE,
        semantic_no_op=False,
        transition_recorded=True,
        observation="RECORDED_UNATTENDED_CYCLE",
    )

    output = tmp_path / "out"
    summary = module.run_unattended_cycle(
        corpus=corpus,
        output_dir=output,
        target="current",
        today=date(2026, 8, 14),
        observed_at=datetime(2026, 8, 14, 15, tzinfo=timezone.utc),
        trigger_event="schedule",
    )

    assert summary["result"] == "COMPLETE"
    assert summary["reason"] == "completed_exact_shadow_cycle"
    assert summary["transition_recorded"] is True
    assert summary["semantic_no_op"] is False
    assert (output / "trust-state.json").is_file()
    assert (output / "trust-receipt.json").is_file()
    assert (output / "cycle-summary.json").is_file()
    for key in (
        "corpus_write_authorized",
        "database_write_authorized",
        "review_write_authorized",
        "production_publish_authorized",
        "deployment_authorized",
        "systemd_change_authorized",
        "bounded_retry_authorized",
    ):
        assert summary[key] is False


def test_no_op_requires_previous_exact_semantic_replay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    corpus, flyer_key, scan = make_corpus(tmp_path)
    status = one_shot(flyer_key, scan)
    patch_completed_cycle(
        monkeypatch,
        module,
        status=status,
        controller_result=module.NO_OP_STATE,
        semantic_no_op=False,
        transition_recorded=False,
        observation="DUPLICATE_WEEK_NOT_COUNTED",
    )

    with pytest.raises(
        module.LidlWeeklyUnattendedCycleError,
        match="controller NO_OP is not an exact semantic no-op",
    ):
        module.run_unattended_cycle(
            corpus=corpus,
            output_dir=tmp_path / "out",
            target="current",
            today=date(2026, 8, 14),
            observed_at=datetime(2026, 8, 14, 16, tzinfo=timezone.utc),
            trigger_event="schedule",
            previous_cycle_dir=previous_bundle(tmp_path, module),
        )


def test_no_op_accepts_only_source_parser_profile_and_semantic_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    corpus, flyer_key, scan = make_corpus(tmp_path)
    status = one_shot(flyer_key, scan)
    patch_completed_cycle(
        monkeypatch,
        module,
        status=status,
        controller_result=module.NO_OP_STATE,
        semantic_no_op=True,
        transition_recorded=False,
        observation="UNCHANGED_SEMANTIC_NO_OP",
    )

    summary = module.run_unattended_cycle(
        corpus=corpus,
        output_dir=tmp_path / "out",
        target="current",
        today=date(2026, 8, 14),
        observed_at=datetime(2026, 8, 14, 16, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous_cycle_dir=previous_bundle(tmp_path, module),
    )

    assert summary["result"] == "COMPLETE"
    assert summary["controller_result"] == module.NO_OP_STATE
    assert summary["semantic_no_op"] is True
    assert summary["transition_recorded"] is False
    assert (
        summary["reason"]
        == "unchanged_source_parser_profile_and_semantic_evidence"
    )


def test_wait_is_observable_and_skips_semantic_and_trust(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()

    def fake_run_controller(**kwargs):
        kwargs["output_dir"].mkdir(parents=True)
        return {"result": module.WAIT_STATE, "reason": "one_shot_wait_source"}

    monkeypatch.setattr(module, "run_controller", fake_run_controller)
    monkeypatch.setattr(
        module,
        "build_semantic_view",
        lambda **kwargs: pytest.fail("semantic view must not run for WAIT"),
    )
    monkeypatch.setattr(
        module,
        "build_state",
        lambda *args, **kwargs: pytest.fail("trust state must not run for WAIT"),
    )

    output = tmp_path / "out"
    summary = module.run_unattended_cycle(
        corpus=tmp_path / "corpus",
        output_dir=output,
        target="current",
        today=date(2026, 8, 14),
        observed_at=datetime(2026, 8, 14, 17, tzinfo=timezone.utc),
        trigger_event="schedule",
    )

    assert summary["result"] == module.WAIT_STATE
    assert summary["reason"] == "one_shot_wait_source"
    assert (output / "cycle-summary.json").is_file()
    assert not (output / "trust-state.json").exists()


def test_previous_bundle_receipt_must_bind_state_before_controller_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_module()
    monkeypatch.setattr(
        module,
        "run_controller",
        lambda **kwargs: pytest.fail("controller must not run with tampered history"),
    )

    with pytest.raises(
        module.LidlWeeklyUnattendedCycleError,
        match="previous trust receipt does not bind previous state bytes",
    ):
        module.run_unattended_cycle(
            corpus=tmp_path / "corpus",
            output_dir=tmp_path / "out",
            target="current",
            today=date(2026, 8, 14),
            observed_at=datetime(2026, 8, 14, 17, tzinfo=timezone.utc),
            trigger_event="schedule",
            previous_cycle_dir=previous_bundle(
                tmp_path,
                module,
                tamper_receipt=True,
            ),
        )


def test_one_shot_path_components_fail_closed(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    corpus, _, scan = make_corpus(tmp_path)
    status = one_shot("../escape", scan)

    def fake_run_controller(**kwargs):
        output = kwargs["output_dir"] / "one-shot"
        output.mkdir(parents=True)
        (output / "one-shot-status.json").write_text(
            json.dumps(status),
            encoding="utf-8",
        )
        return {"result": module.READY_STATE, "reason": "new_exact_shadow_input"}

    monkeypatch.setattr(module, "run_controller", fake_run_controller)

    with pytest.raises(
        module.LidlWeeklyUnattendedCycleError,
        match="flyer_key is unsafe",
    ):
        module.run_unattended_cycle(
            corpus=corpus,
            output_dir=tmp_path / "out",
            target="current",
            today=date(2026, 8, 14),
            observed_at=datetime(2026, 8, 14, 17, tzinfo=timezone.utc),
            trigger_event="schedule",
        )
