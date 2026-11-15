from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "edeka_monday_cutover_readonly_preflight.py"
PLANNER = ROOT / "tools" / "edeka_weekly_monitor_activation_plan.py"
MONDAY_SOURCE_TIMER = ROOT / "config" / "hermes-edeka-weekly-monitor-monday.timer.example"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_source_candidate_and_pure_cutover_plan(tmp_path: Path) -> None:
    cutover = load_module(SCRIPT, "edeka_cutover_pure")
    planner = load_module(PLANNER, "edeka_old_schedule_planner")

    old = tmp_path / "generated-old"
    plan = planner.build_activation_plan(
        output_dir=old,
        repo_root=Path("/home/andris/hermes-deals-audit-source-edeka"),
        repo_sha=cutover.OLD_SOURCE,
        python_path=Path("/usr/bin/python3"),
        shadow_evidence_root=Path("/home/andris/hermes-deals-shadow-evidence/edeka"),
        monitor_evidence_root=Path("/home/andris/hermes-deals-edeka-weekly-monitor"),
        cache_root=Path("/home/andris/.cache/hermes-deals-edeka-shadow"),
        on_calendar=cutover.OLD_CALENDAR,
        retry_delay="30min", retry_window="6h", max_attempts=3,
        timeout_start="50min", runner_timeout_seconds=2700,
    )
    old_units = {key: (old / key).read_bytes() for key in cutover.OLD_UNIT_HASHES}
    assert plan["unit_sha256"] == cutover.OLD_UNIT_HASHES
    assert MONDAY_SOURCE_TIMER.read_bytes() == cutover.MONDAY_TIMER_BYTES
    assert cutover.digest(cutover.MONDAY_TIMER_BYTES) == cutover.NEW_TIMER_SHA256

    registration = {
        "schema_version": 1,
        "registration_sha": cutover.OLD_SOURCE,
        "repo_root": str(cutover.AUDIT_ROOT),
        "planner_blob": "749f4d2ff09d50a9d53e45887013d6d4d79ed69a",
        "runtime_blob": "4c863cf516a7de6cf8684b9b3ba3f1eb22785141",
        "installer_blob": "91ddc076ec6407b567a3ae3300bef0e8a7adfca5",
        "schedule": {
            "on_calendar": cutover.OLD_CALENDAR,
            "retry_delay": "30min",
            "retry_window": "6h",
            "max_attempts": 3,
            "timeout_start": "50min",
            "runner_timeout_seconds": 2700,
        },
        "unit_sha256": dict(cutover.OLD_UNIT_HASHES),
        "shadow_evidence_root": "/home/andris/hermes-deals-shadow-evidence/edeka",
        "monitor_evidence_root": "/home/andris/hermes-deals-edeka-weekly-monitor",
        "cache_root": "/home/andris/.cache/hermes-deals-edeka-shadow",
        "unit_dir": "/etc/systemd/system",
        "registration_scope": "unit_files_only_no_manager_reload",
    }
    for key in cutover.FALSE_REGISTRATION_FLAGS:
        registration[key] = False
    expected_fp = cutover.digest(cutover.canonical_json(registration))
    assert expected_fp == cutover.OLD_FINGERPRINT
    registration["registration_fingerprint_sha256"] = expected_fp

    control = {
        "schema_version": 1,
        "control": "edeka-weekly-monitor-control-v1",
        "issue_number": 26,
        "control_sha": cutover.OLD_CONTROL_SHA,
        "dispatcher_blob": cutover.OLD_DISPATCHER_BLOB,
        "dispatcher_sha256": cutover.OLD_DISPATCHER_SHA256,
        "registration_sha": cutover.OLD_SOURCE,
        "registration_fingerprint_sha256": cutover.OLD_FINGERPRINT,
        "root_registration_only": True,
    }
    for key in cutover.FALSE_CONTROL_FLAGS:
        control[key] = False

    # Build a no-write synthetic pair with the *known* on-host SHA256 checks.
    # The real dispatcher/sudoers bytes never leave rpi5; their hashes are
    # verified by the read-only CLI. This pure test checks the same branches
    # by patching only the expected hash constants in the isolated module.
    cutover.OLD_DISPATCHER_SHA256 = cutover.digest(b"synthetic-dispatcher")
    cutover.OLD_SUDOERS_SHA256 = cutover.digest(b"synthetic-sudoers")
    control["dispatcher_sha256"] = cutover.OLD_DISPATCHER_SHA256
    input_args = dict(
        service=old_units[cutover.SERVICE],
        timer=old_units[cutover.TIMER],
        alert=old_units[cutover.ALERT],
        registration=registration,
        control=control,
        dispatcher=b"synthetic-dispatcher",
        sudoers=b"synthetic-sudoers",
        reviewed_source_sha=cutover.REVIEWED_SOURCE,
    )
    registration_before = deepcopy(registration)
    control_before = deepcopy(control)
    result = cutover.build_readonly_proposal(**input_args)
    assert registration == registration_before
    assert control == control_before
    assert result["result"] == "READ_ONLY_PREFLIGHT_PASS"
    assert result["reviewed_source_target"] == cutover.REVIEWED_SOURCE
    assert result["candidate_unit_sha256"][cutover.TIMER] == cutover.NEW_TIMER_SHA256
    assert result["candidate_unit_sha256"][cutover.SERVICE] != cutover.OLD_UNIT_HASHES[cutover.SERVICE]
    assert result["candidate_unit_sha256"][cutover.ALERT] == cutover.OLD_UNIT_HASHES[cutover.ALERT]
    assert result["registration_fingerprint_candidate"] != cutover.OLD_FINGERPRINT
    assert result["source_or_host_mutation_performed"] is False
    assert result["live_mutation_authorized"] is False
    assert result["live_mutation_ready"] is False
    assert result["control_dispatcher_and_sudoers_rebinding_required"] is True

    with pytest.raises(cutover.DriftError, match="reviewed target source pin drift"):
        cutover.build_readonly_proposal(**{
            **input_args, "reviewed_source_sha": cutover.OLD_SOURCE,
        })
    with pytest.raises(cutover.DriftError, match="timer baseline SHA256 drift"):
        cutover.build_readonly_proposal(**{
            **input_args, "timer": input_args["timer"] + b"extra=1\n",
        })
    with pytest.raises(cutover.DriftError, match="registered source SHA drift"):
        cutover.build_readonly_proposal(**{
            **input_args, "registration": {
                **registration, "registration_sha": "0" * 40,
            },
        })
    with pytest.raises(cutover.DriftError, match="unsafe registration flag"):
        cutover.build_readonly_proposal(**{
            **input_args, "registration": {
                **registration, "production_database_write_performed": True,
            },
        })
    with pytest.raises(cutover.DriftError, match="control source SHA drift"):
        cutover.build_readonly_proposal(**{
            **input_args, "control": {**control, "control_sha": "0" * 40},
        })


def test_no_live_commands_or_implicit_mutating_interface() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "systemctl", "daemon-reload", "reset-failed", "git fetch",
        "git checkout", "git reset", "systemctl restart", "os.replace(",
        "shutil.copy", "subprocess.Popen(", "os.chown(", "os.chmod(",
    ):
        assert forbidden not in source
    assert "live_mutation_ready" in source
    assert "GIT_OPTIONAL_LOCKS" in source
    assert "read_root_regular" in source
