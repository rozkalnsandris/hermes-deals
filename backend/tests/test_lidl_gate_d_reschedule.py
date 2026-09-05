from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "tools" / "runner" / "reschedule_lidl_gate_d.py"

OLD_PLAN = "28277e25db006c82587b52bad02939d17ceb5eb455ec059e2cdc2ca5ff68ea31"
NEW_PLAN = "651301e004e39360c7198721b32c299c58d1720c9409f06189e265ff311c4bb4"
OLD_SCHEDULE = "Mon *-*-* 06:15:00 Europe/Berlin"
NEW_SCHEDULE = "Sun *-*-* 00:10:00 Europe/Berlin"
NEW_TIMER_SHA = "beedb229d2203ab239f10de2772e086de58e4b7032e705897d064978aa840597"


def load_module():
    spec = importlib.util.spec_from_file_location("lidl_gate_d_reschedule", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["lidl_gate_d_reschedule"] = module
    spec.loader.exec_module(module)
    return module


def old_config(module) -> dict:
    return {
        "schema_version": 1,
        "control": "lidl-gate-d-control",
        "issue_number": 24,
        "bridge_pr": 656,
        "registration_sha": module.REGISTRATION_SHA,
        "plan_fingerprint": OLD_PLAN,
        "repo_root": "/home/andris/hermes-deals-audit-source-lidl",
        "python_path": "/usr/bin/python3",
        "corpus_root": "/home/andris/hermes-deals-lidl-corpus",
        "evidence_root": "/home/andris/hermes-deals-lidl-weekly-evidence",
        "target": "current",
        "schedule": {
            "on_calendar": OLD_SCHEDULE,
            "retry_delay": "30min",
            "retry_window": "6h",
            "max_attempts": 3,
            "timeout_start": "45min",
        },
        "units": {
            module.SERVICE_UNIT: {
                "path": str(module.STAGED_ROOT / module.SERVICE_UNIT),
                "sha256": module.SERVICE_SHA256,
            },
            module.TIMER_UNIT: {
                "path": str(module.STAGED_ROOT / module.TIMER_UNIT),
                "sha256": module.OLD_TIMER_SHA256,
            },
            module.ALERT_UNIT: {
                "path": str(module.STAGED_ROOT / module.ALERT_UNIT),
                "sha256": module.ALERT_SHA256,
            },
        },
        "activation_requires_explicit_owner_authorization": True,
        "root_registration_only": True,
        "production_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
    }


def test_exact_registered_and_new_plan_identities() -> None:
    module = load_module()
    config = old_config(module)
    assert module.plan_fingerprint(config) == OLD_PLAN

    migrated = module.build_new_config(config)
    assert module.plan_fingerprint(migrated) == NEW_PLAN
    assert migrated["plan_fingerprint"] == NEW_PLAN
    assert migrated["schedule"]["on_calendar"] == NEW_SCHEDULE
    assert migrated["units"][module.TIMER_UNIT]["sha256"] == NEW_TIMER_SHA


def test_reschedule_changes_only_schedule_timer_hash_and_plan() -> None:
    module = load_module()
    before = old_config(module)
    before_copy = copy.deepcopy(before)
    after = module.build_new_config(before)

    assert before == before_copy
    assert set(after) == set(before)
    for key in before:
        if key not in {"plan_fingerprint", "schedule", "units"}:
            assert after[key] == before[key]

    expected_schedule = dict(before["schedule"])
    expected_schedule["on_calendar"] = NEW_SCHEDULE
    assert after["schedule"] == expected_schedule

    for name in module.UNIT_NAMES:
        assert after["units"][name]["path"] == before["units"][name]["path"]
        if name == module.TIMER_UNIT:
            assert after["units"][name]["sha256"] == NEW_TIMER_SHA
        else:
            assert after["units"][name] == before["units"][name]


def test_new_timer_bytes_are_exact_and_persistent() -> None:
    module = load_module()
    assert module.NEW_SCHEDULE == NEW_SCHEDULE
    assert hashlib.sha256(module.NEW_TIMER_BYTES).hexdigest() == NEW_TIMER_SHA
    text = module.NEW_TIMER_BYTES.decode("utf-8")
    assert f"OnCalendar={NEW_SCHEDULE}" in text
    assert "Persistent=true" in text
    assert "AccuracySec=5min" in text


def test_old_staging_is_archived_not_overwritten() -> None:
    module = load_module()
    source = MIGRATION.read_text(encoding="utf-8")
    assert "os.rename(STAGED_ROOT, ARCHIVED_ROOT)" in source
    assert "os.rename(new_staged, STAGED_ROOT)" in source
    assert module.OLD_PLAN_FINGERPRINT in module.ARCHIVED_ROOT.name
    assert module.ARCHIVED_ROOT != module.STAGED_ROOT


def test_live_reschedule_requires_explicit_persistent_catchup_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    with pytest.raises(module.LidlGateDRescheduleError, match="catch-up authority"):
        module.reschedule(
            "a" * 40,
            OLD_PLAN,
            NEW_PLAN,
            "persistent-catchup=forbidden",
        )


def test_mutation_scope_excludes_production_data_and_enablement_changes() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert '["/usr/bin/systemctl", "enable"' not in source
    assert '["/usr/bin/systemctl", "disable"' not in source
    assert "/usr/bin/psql" not in source
    assert "/usr/bin/docker" not in source
    assert '"production_database_write_performed": False' in source
    assert '"review_write_performed": False' in source
    assert '"publication_write_performed": False' in source
    assert '"production_deploy_performed": False' in source


def test_new_config_serialization_does_not_change_fingerprint() -> None:
    module = load_module()
    config = module.build_new_config(old_config(module))
    pretty = json.dumps(config, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    reparsed = json.loads(pretty)
    assert module.plan_fingerprint(reparsed) == NEW_PLAN
