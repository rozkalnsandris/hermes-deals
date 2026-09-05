from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "tools/runner/reschedule_edeka_weekly_monitor.py"
DISPATCHER_PATH = ROOT / "tools/runner/edeka_weekly_monitor_control.py"
AUTHORIZER_PATH = ROOT / "tools/github_edeka_weekly_monitor_control.py"

OLD_FP = "f724ad3c5d84e469847f462512fb96128dbd1e44f679f52606c363e9a70762fb"
NEW_FP = "970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947"
NEW_SCHEDULE = "Sun *-*-* 00:10:00 Europe/Berlin"
NEW_TIMER_SHA = "6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_reschedule_constants_are_cross_bound() -> None:
    migration = load_module(MIGRATION_PATH, "edeka_reschedule")
    dispatcher = load_module(DISPATCHER_PATH, "edeka_dispatcher")
    authorizer = load_module(AUTHORIZER_PATH, "edeka_authorizer")

    assert migration.NEW_SCHEDULE == NEW_SCHEDULE
    assert migration.NEW_FINGERPRINT == NEW_FP
    assert migration.NEW_TIMER_SHA256 == NEW_TIMER_SHA
    assert hashlib.sha256(migration.NEW_TIMER_BYTES).hexdigest() == NEW_TIMER_SHA

    assert dispatcher.EXPECTED_SCHEDULE["on_calendar"] == NEW_SCHEDULE
    assert dispatcher.EXPECTED_UNIT_SHA256[dispatcher.TIMER_UNIT] == NEW_TIMER_SHA
    assert dispatcher.EXPECTED_REGISTRATION_FINGERPRINT == NEW_FP
    assert authorizer.EXPECTED_REGISTRATION_FINGERPRINT == NEW_FP


def test_new_registration_is_exact_one_field_schedule_migration() -> None:
    migration = load_module(MIGRATION_PATH, "edeka_reschedule_registration")
    old = {
        "schema_version": 1,
        "registration_sha": migration.REGISTRATION_SHA,
        "repo_root": str(migration.SOURCE_REPO),
        "planner_blob": "749f4d2ff09d50a9d53e45887013d6d4d79ed69a",
        "runtime_blob": "4c863cf516a7de6cf8684b9b3ba3f1eb22785141",
        "installer_blob": "91ddc076ec6407b567a3ae3300bef0e8a7adfca5",
        "schedule": {
            "on_calendar": migration.OLD_SCHEDULE,
            "retry_delay": "30min",
            "retry_window": "6h",
            "max_attempts": 3,
            "timeout_start": "50min",
            "runner_timeout_seconds": 2700,
        },
        "unit_sha256": {
            migration.SERVICE_UNIT: migration.SERVICE_SHA256,
            migration.TIMER_UNIT: migration.OLD_TIMER_SHA256,
            migration.FAILURE_UNIT: migration.FAILURE_SHA256,
        },
        "shadow_evidence_root": "/home/andris/hermes-deals-shadow-evidence/edeka",
        "monitor_evidence_root": "/home/andris/hermes-deals-edeka-weekly-monitor",
        "cache_root": "/home/andris/.cache/hermes-deals-edeka-shadow",
        "unit_dir": str(migration.UNIT_DIR),
        "registration_scope": "unit_files_only_no_manager_reload",
        "daemon_reload_performed": False,
        "timer_enable_performed": False,
        "timer_start_performed": False,
        "source_refetch_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
        "registration_fingerprint_sha256": OLD_FP,
    }
    old_copy = json.loads(json.dumps(old))
    new = migration.build_new_registration(old)

    assert old == old_copy
    assert new["registration_fingerprint_sha256"] == NEW_FP
    assert new["schedule"]["on_calendar"] == NEW_SCHEDULE
    assert new["unit_sha256"][migration.TIMER_UNIT] == NEW_TIMER_SHA

    old_core = {key: value for key, value in old.items() if key != "registration_fingerprint_sha256"}
    new_core = {key: value for key, value in new.items() if key != "registration_fingerprint_sha256"}
    assert old_core.keys() == new_core.keys()
    for key in old_core:
        if key not in {"schedule", "unit_sha256"}:
            assert new_core[key] == old_core[key]
    assert {**old_core["schedule"], "on_calendar": NEW_SCHEDULE} == new_core["schedule"]
    assert {**old_core["unit_sha256"], migration.TIMER_UNIT: NEW_TIMER_SHA} == new_core["unit_sha256"]


def test_authorizer_accepts_only_new_fingerprint() -> None:
    authorizer = load_module(AUTHORIZER_PATH, "edeka_authorizer_parse")
    base = (
        "/hermes-edeka monitor disable "
        "control=" + "a" * 40 + " "
        "registration=" + authorizer.EXPECTED_REGISTRATION_SHA + " "
        "fingerprint={fingerprint} refetch=forbidden retries=forbidden"
    )
    command = authorizer.parse_comment(base.format(fingerprint=NEW_FP))
    assert command.fingerprint == NEW_FP
    with pytest.raises(authorizer.BridgeAuthorizationError):
        authorizer.parse_comment(base.format(fingerprint=OLD_FP))


def test_reschedule_mutation_scope_is_bounded() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert '["/usr/bin/systemctl", "enable"' not in source
    assert '["/usr/bin/systemctl", "disable"' not in source
    assert '["/usr/bin/systemctl", "restart"' not in source
    assert "/usr/bin/psql" not in source
    assert "/usr/bin/docker" not in source
    assert "production_database_write_performed" in source
    assert '"production_database_write_performed": False' in source
    assert '"review_write_performed": False' in source
    assert '"publication_write_performed": False' in source
    assert '"production_deploy_performed": False' in source


def test_reschedule_requires_explicit_persistent_catchup_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = load_module(MIGRATION_PATH, "edeka_reschedule_authority")
    monkeypatch.setattr(migration.os, "geteuid", lambda: 0)
    with pytest.raises(migration.RescheduleError, match="catch-up authority"):
        migration.reschedule("a" * 40, OLD_FP, NEW_FP, "persistent-catchup=forbidden")
