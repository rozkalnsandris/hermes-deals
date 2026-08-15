from __future__ import annotations

from datetime import date, datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SCRIPT = ROOT / "tools" / "edeka_weekly_monitor_runtime.py"
PLANNER_SCRIPT = ROOT / "tools" / "edeka_weekly_monitor_activation_plan.py"


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_campaign_freshness_classification_is_deterministic() -> None:
    runtime = load_script(RUNTIME_SCRIPT, "edeka_monitor_classify")

    assert runtime.classify_campaign(
        date(2026, 8, 10), date(2026, 8, 15), date(2026, 8, 15)
    ) == ("COMPLETE", "campaign_current", 0)
    assert runtime.classify_campaign(
        date(2026, 8, 17), date(2026, 8, 22), date(2026, 8, 16)
    ) == ("COMPLETE", "future_campaign_published", 0)
    assert runtime.classify_campaign(
        date(2026, 8, 10), date(2026, 8, 15), date(2026, 8, 17)
    ) == ("STALE", "campaign_expired", 2)


def _write_cycle(root: Path, *, valid_from: str, valid_until: str) -> Path:
    run = root / "20260815T120000Z-abc"
    cycle = run / "cycle"
    cycle.mkdir(parents=True)
    evidence = {
        "result": "pass",
        "source": {
            "source_chain": "edeka",
            "scope": "family_primary_edeka",
            "public_market_id": "071897",
            "internal_market_id": "587881",
            "store_name": "EDEKA Patzer",
            "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
            "snapshot_id": "snapshot",
            "manifest_sha256": "a" * 64,
            "valid_from": valid_from,
            "valid_until": valid_until,
        },
        "isolated_persistence": {
            "parsed_offer_count": 194,
            "first_write_offer_delta": 194,
            "same_snapshot_replay_offer_delta": 0,
            "production_database_write": False,
        },
        "safety": {
            "production_deployment": False,
            "production_database_write": False,
            "review_write": False,
            "publication_write": False,
            "scheduler_activation": False,
        },
    }
    (cycle / "cycle-evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    return run


def test_cycle_evidence_rejects_safety_drift_and_detects_stale(tmp_path: Path) -> None:
    runtime = load_script(RUNTIME_SCRIPT, "edeka_monitor_cycle")
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    run = _write_cycle(shadow, valid_from="2026-08-10", valid_until="2026-08-15")

    campaign, result, reason, stale_days = runtime._validate_cycle_evidence(
        run, shadow.resolve(), date(2026, 8, 17)
    )
    assert campaign["parsed_offer_count"] == 194
    assert result == "STALE"
    assert reason == "campaign_expired"
    assert stale_days == 2

    evidence_path = run / "cycle" / "cycle-evidence.json"
    value = json.loads(evidence_path.read_text(encoding="utf-8"))
    value["safety"]["production_database_write"] = True
    evidence_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(runtime.EdekaWeeklyMonitorError, match="production_database_write"):
        runtime._validate_cycle_evidence(run, shadow.resolve(), date(2026, 8, 17))


def test_monitor_nonzero_shadow_runner_is_sanitized_blocked(tmp_path: Path, monkeypatch) -> None:
    runtime = load_script(RUNTIME_SCRIPT, "edeka_monitor_blocked")
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "run-hermes-deals-edeka-shadow-cycle-v01.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    shadow = tmp_path / "shadow"
    monitor = tmp_path / "monitor"
    shadow.mkdir(mode=0o700)
    monitor.mkdir(mode=0o700)
    os.chmod(shadow, 0o700)
    os.chmod(monitor, 0o700)

    monkeypatch.setattr(runtime, "verify_exact_checkout", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runtime,
        "_run_shadow_cycle",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["shadow"], returncode=1, stdout=b"private stdout", stderr=b"private stderr"
        ),
    )

    receipt, run_dir, exit_code = runtime.run_monitor_cycle(
        repo_root=repo,
        expected_repo_sha="b" * 40,
        shadow_evidence_root=shadow,
        monitor_evidence_root=monitor,
        observed_at=datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc),
    )

    assert exit_code == 30
    assert receipt["result"] == "BLOCKED"
    assert receipt["reason"] == "shadow_cycle_nonzero"
    assert receipt["shadow_stdout_sha256"] == runtime._sha_bytes(b"private stdout")
    assert receipt["shadow_stderr_sha256"] == runtime._sha_bytes(b"private stderr")
    assert "private" not in (run_dir / "monitor-receipt.json").read_text(encoding="utf-8")
    assert receipt["production_database_write_performed"] is False
    assert receipt["scheduler_systemd_change_performed"] is False


def build_plan(tmp_path: Path, planner, name: str = "plan"):
    return planner.build_activation_plan(
        output_dir=tmp_path / name,
        repo_root=Path("/home/andris/hermes-deals-audit-source-edeka"),
        repo_sha="c" * 40,
        python_path=Path("/usr/bin/python3"),
        shadow_evidence_root=Path("/home/andris/hermes-deals-shadow-evidence/edeka"),
        monitor_evidence_root=Path("/home/andris/hermes-deals-edeka-weekly-monitor"),
        cache_root=Path("/home/andris/.cache/hermes-deals-edeka-shadow"),
        on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="50min",
    )


def test_activation_plan_is_non_activating_bounded_and_reversible(tmp_path: Path) -> None:
    planner = load_script(PLANNER_SCRIPT, "edeka_monitor_plan")
    plan = build_plan(tmp_path, planner)
    root = tmp_path / "plan"
    service = (root / planner.SERVICE_UNIT).read_text(encoding="utf-8")
    timer = (root / planner.TIMER_UNIT).read_text(encoding="utf-8")

    assert "Restart=on-failure" in service
    assert "RestartSec=30min" in service
    assert "StartLimitIntervalSec=6h" in service
    assert "StartLimitBurst=3" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=read-only" in service
    assert "ReadWritePaths=/home/andris/hermes-deals-shadow-evidence/edeka /home/andris/hermes-deals-edeka-weekly-monitor /home/andris/.cache/hermes-deals-edeka-shadow" in service
    assert "OnCalendar=Mon *-*-* 06:15:00 Europe/Berlin" in timer
    assert "Persistent=true" in timer

    assert plan["activation_requires_explicit_owner_authorization"] is True
    for key in (
        "source_refetch_authorized",
        "systemd_change_authorized",
        "systemd_change_performed",
        "bounded_retry_authorized",
        "production_database_write_authorized",
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
    assert ["systemctl", "enable", "--now", planner.TIMER_UNIT] in activation_argv
    assert plan["disable_steps"][0]["argv"] == [
        "systemctl", "disable", "--now", planner.TIMER_UNIT
    ]
    assert plan["rollback_steps"][0]["argv"] == [
        "systemctl", "disable", "--now", planner.TIMER_UNIT
    ]
    assert plan["rollback_preserves_shadow_evidence_root"] is True
    assert plan["rollback_preserves_monitor_evidence_root"] is True
    assert plan["observability"]["stale_exit_code"] == 20
    assert plan["observability"]["blocked_exit_code"] == 30


def test_activation_plan_is_deterministic_and_rejects_schedule_injection(tmp_path: Path) -> None:
    planner = load_script(PLANNER_SCRIPT, "edeka_monitor_deterministic")
    first = build_plan(tmp_path, planner, "one")
    second = build_plan(tmp_path, planner, "two")
    assert first["unit_sha256"] == second["unit_sha256"]
    for name in (planner.SERVICE_UNIT, planner.TIMER_UNIT, planner.ALERT_UNIT):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()

    with pytest.raises(planner.EdekaWeeklyMonitorActivationPlanError, match="one line"):
        planner.build_activation_plan(
            output_dir=tmp_path / "bad",
            repo_root=Path("/repo"),
            repo_sha="d" * 40,
            python_path=Path("/usr/bin/python3"),
            shadow_evidence_root=Path("/shadow"),
            monitor_evidence_root=Path("/monitor"),
            cache_root=Path("/cache"),
            on_calendar="weekly\nExecStart=/bin/sh",
            retry_delay="30min",
            retry_window="6h",
            max_attempts=3,
            timeout_start="50min",
        )


def test_source_contract_does_not_activate_systemd_or_write_production() -> None:
    runtime_source = RUNTIME_SCRIPT.read_text(encoding="utf-8")
    planner_source = PLANNER_SCRIPT.read_text(encoding="utf-8")

    assert "systemctl" not in runtime_source
    assert "sudo" not in runtime_source
    assert "production_database_write_performed" in runtime_source
    assert '"source_refetch_authorized": False' in planner_source
    assert '"systemd_change_authorized": False' in planner_source
    assert '"production_database_write_authorized": False' in planner_source
