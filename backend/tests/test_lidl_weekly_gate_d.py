from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SCRIPT = ROOT / "tools" / "lidl_weekly_gate_d_runtime.py"
PLANNER_SCRIPT = ROOT / "tools" / "lidl_weekly_gate_d_activation_plan.py"


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_digest(value: dict) -> str:
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_complete_cycle(root: Path, runtime, *, generated_at: str, tamper: bool = False) -> None:
    (root / "controller").mkdir(parents=True)
    (root / "controller" / "controller-manifest.json").write_text("{}\n", encoding="utf-8")
    summary = {
        "result": "COMPLETE",
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "deployment_authorized": False,
        "systemd_change_authorized": False,
        "bounded_retry_authorized": False,
    }
    (root / "cycle-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    state = {
        "schema_version": 1,
        "strategy": runtime.TRUST_STATE_STRATEGY,
        "generated_at": generated_at,
        "trigger_event": "schedule",
        "production_write_authorized": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_performed": False,
        "deployment_performed": False,
        "systemd_change_performed": False,
        "scheduled_cycles": [],
    }
    state_path = root / "trust-state.json"
    state_path.write_bytes(runtime._canonical_bytes(state))
    receipt = {
        "schema_version": 1,
        "strategy": runtime.TRUST_RECEIPT_STRATEGY,
        "state_sha256": "f" * 64 if tamper else runtime._sha_file(state_path),
    }
    (root / "trust-receipt.json").write_bytes(runtime._canonical_bytes(receipt))


def test_runtime_selects_latest_valid_scheduled_complete_cycle(tmp_path: Path) -> None:
    runtime = load_script(RUNTIME_SCRIPT, "gate_d_runtime_select")
    root = tmp_path / "evidence"
    root.mkdir(mode=0o700)
    old = root / "lidl-weekly-old"
    new = root / "lidl-weekly-new"
    tampered = root / "lidl-weekly-tampered"
    current = root / "lidl-weekly-current"
    write_complete_cycle(old, runtime, generated_at="2026-08-10T06:00:00+00:00")
    write_complete_cycle(new, runtime, generated_at="2026-08-11T06:00:00+00:00")
    write_complete_cycle(tampered, runtime, generated_at="2026-08-12T06:00:00+00:00", tamper=True)
    current.mkdir()

    selected = runtime.select_previous_cycle(root, current)

    assert selected == new.resolve()


def test_runtime_wait_is_nonzero_and_receipted(tmp_path: Path, monkeypatch) -> None:
    runtime = load_script(RUNTIME_SCRIPT, "gate_d_runtime_wait")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "backend").mkdir()
    monkeypatch.setattr(runtime, "verify_exact_checkout", lambda *args, **kwargs: None)

    fake = types.ModuleType("lidl_weekly_unattended_cycle")
    fake.run_unattended_cycle = lambda **kwargs: {
        "result": "WAIT",
        "reason": "one_shot_wait_source",
    }
    monkeypatch.setitem(sys.modules, "lidl_weekly_unattended_cycle", fake)

    receipt, run_dir, exit_code = runtime.run_scheduled_runtime(
        repo_root=repo,
        expected_repo_sha="a" * 40,
        corpus=corpus,
        evidence_root=evidence,
        target="current",
        observed_at=datetime(2026, 8, 14, 16, 30, tzinfo=timezone.utc),
    )

    assert exit_code == 20
    assert receipt["result"] == "WAIT"
    assert receipt["trigger_event"] == "schedule"
    assert receipt["systemd_change_authorized"] is False
    assert (run_dir / "runtime-receipt.json").is_file()


def test_runtime_rejects_unsafe_evidence_permissions(tmp_path: Path, monkeypatch) -> None:
    runtime = load_script(RUNTIME_SCRIPT, "gate_d_runtime_mode")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o755)
    os.chmod(evidence, 0o755)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(runtime, "verify_exact_checkout", lambda *args, **kwargs: None)

    with pytest.raises(runtime.LidlWeeklyGateDRuntimeError, match="mode must be 0700"):
        runtime.run_scheduled_runtime(
            repo_root=repo,
            expected_repo_sha="a" * 40,
            corpus=corpus,
            evidence_root=evidence,
            target="current",
        )


def build_plan(tmp_path: Path, planner, name: str = "plan"):
    return planner.build_activation_plan(
        output_dir=tmp_path / name,
        repo_root=Path("/home/andris/hermes-deals-audit-source-lidl"),
        repo_sha="b" * 40,
        python_path=Path("/usr/bin/python3"),
        corpus_root=Path("/home/andris/hermes-deals-lidl-corpus"),
        evidence_root=Path("/home/andris/hermes-deals-lidl-weekly-evidence"),
        on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="45min",
    )


def test_activation_plan_is_non_activating_bounded_and_reversible(tmp_path: Path) -> None:
    planner = load_script(PLANNER_SCRIPT, "gate_d_plan")
    plan = build_plan(tmp_path, planner)
    root = tmp_path / "plan"
    service = (root / planner.SERVICE_UNIT).read_text(encoding="utf-8")
    timer = (root / planner.TIMER_UNIT).read_text(encoding="utf-8")
    alert = (root / planner.ALERT_UNIT).read_text(encoding="utf-8")

    assert "Restart=on-failure" in service
    assert "RestartSec=30min" in service
    assert "StartLimitIntervalSec=6h" in service
    assert "StartLimitBurst=3" in service
    assert "--expected-repo-sha " + "b" * 40 in service
    assert "lidl_weekly_gate_d_runtime.py" in service
    assert "OnCalendar=Mon *-*-* 06:15:00 Europe/Berlin" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert "logger -p user.err -t hermes-lidl-weekly-failure" in alert
    assert plan["activation_requires_explicit_owner_authorization"] is True
    for key in (
        "systemd_change_authorized",
        "systemd_change_performed",
        "bounded_retry_authorized",
        "production_write_authorized",
        "database_write_authorized",
        "review_write_authorized",
        "publication_authorized",
        "deployment_authorized",
    ):
        assert plan[key] is False

    activation_argv = [step["argv"] for step in plan["activation_steps"]]
    assert activation_argv[0] == [
        "systemd-analyze", "calendar", "Mon *-*-* 06:15:00 Europe/Berlin"
    ]
    assert activation_argv[1][0:2] == ["systemd-analyze", "verify"]
    assert plan["preflight_before_mutation"] is True
    assert ["systemctl", "enable", "--now", planner.TIMER_UNIT] in activation_argv
    assert plan["disable_steps"][0]["argv"] == [
        "systemctl", "disable", "--now", planner.TIMER_UNIT
    ]
    assert plan["rollback_steps"][0]["argv"] == [
        "systemctl", "disable", "--now", planner.TIMER_UNIT
    ]
    assert plan["rollback_preserves_evidence_root"] is True
    assert plan["observability"]["runner_wait_exit_code"] == 20
    assert plan["observability"]["runner_blocked_exit_code"] == 30
    assert plan["observability"]["review_pending_evidence"] == "semantic/review-required.tsv"


def test_activation_plan_units_are_deterministic(tmp_path: Path) -> None:
    planner = load_script(PLANNER_SCRIPT, "gate_d_plan_deterministic")
    first = build_plan(tmp_path, planner, "one")
    second = build_plan(tmp_path, planner, "two")

    assert first["unit_sha256"] == second["unit_sha256"]
    for name in (planner.SERVICE_UNIT, planner.TIMER_UNIT, planner.ALERT_UNIT):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def test_activation_plan_rejects_multiline_schedule(tmp_path: Path) -> None:
    planner = load_script(PLANNER_SCRIPT, "gate_d_plan_schedule")
    with pytest.raises(planner.LidlWeeklyGateDActivationPlanError, match="one line"):
        planner.build_activation_plan(
            output_dir=tmp_path / "out",
            repo_root=Path("/repo"),
            repo_sha="c" * 40,
            python_path=Path("/usr/bin/python3"),
            corpus_root=Path("/corpus"),
            evidence_root=Path("/evidence"),
            on_calendar="weekly\nExecStart=/bin/sh",
            retry_delay="30min",
            retry_window="6h",
            max_attempts=3,
            timeout_start="45min",
        )


def test_activation_plan_rejects_relative_or_nonempty_output(tmp_path: Path) -> None:
    planner = load_script(PLANNER_SCRIPT, "gate_d_plan_paths")
    with pytest.raises(planner.LidlWeeklyGateDActivationPlanError, match="repo root must be absolute"):
        planner.build_activation_plan(
            output_dir=tmp_path / "out-relative",
            repo_root=Path("repo"),
            repo_sha="c" * 40,
            python_path=Path("/usr/bin/python3"),
            corpus_root=Path("/corpus"),
            evidence_root=Path("/evidence"),
            on_calendar="weekly",
            retry_delay="30min",
            retry_window="6h",
            max_attempts=3,
            timeout_start="45min",
        )

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "sentinel").write_text("keep", encoding="utf-8")
    with pytest.raises(planner.LidlWeeklyGateDActivationPlanError, match="must be empty"):
        planner.build_activation_plan(
            output_dir=occupied,
            repo_root=Path("/repo"),
            repo_sha="c" * 40,
            python_path=Path("/usr/bin/python3"),
            corpus_root=Path("/corpus"),
            evidence_root=Path("/evidence"),
            on_calendar="weekly",
            retry_delay="30min",
            retry_window="6h",
            max_attempts=3,
            timeout_start="45min",
        )
