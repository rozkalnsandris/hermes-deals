from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import stat
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[2]
CUTOVER = ROOT / "tools" / "runner" / "edeka_monday_forward_cutover.py"
HELPER = ROOT / "tools" / "edeka_monday_cutover_readonly_preflight.py"
PLANNER = ROOT / "tools" / "edeka_weekly_monitor_activation_plan.py"
DISPATCHER = ROOT / "tools" / "runner" / "edeka_weekly_monitor_control_monday.py"


def module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    import sys
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def setup_old_state(tmp_path: Path):
    cutover = module(CUTOVER, "edeka_forward_cutover")
    helper = module(HELPER, "edeka_forward_preflight")
    planner = module(PLANNER, "edeka_forward_planner")
    plan = planner.build_activation_plan(
        output_dir=tmp_path / "old",
        repo_root=cutover.APP_ROOT,
        repo_sha=cutover.OLD_SOURCE,
        python_path=Path("/usr/bin/python3"),
        shadow_evidence_root=Path("/home/andris/hermes-deals-shadow-evidence/edeka"),
        monitor_evidence_root=Path("/home/andris/hermes-deals-edeka-weekly-monitor"),
        cache_root=Path("/home/andris/.cache/hermes-deals-edeka-shadow"),
        on_calendar=helper.OLD_CALENDAR,
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="50min",
        runner_timeout_seconds=2700,
    )
    assert plan["unit_sha256"] == helper.OLD_UNIT_HASHES

    old_reg = {
        "schema_version": 1,
        "registration_sha": cutover.OLD_SOURCE,
        "repo_root": str(cutover.APP_ROOT),
        "planner_blob": "749f4d2ff09d50a9d53e45887013d6d4d79ed69a",
        "runtime_blob": "4c863cf516a7de6cf8684b9b3ba3f1eb22785141",
        "installer_blob": "91ddc076ec6407b567a3ae3300bef0e8a7adfca5",
        "schedule": {
            "on_calendar": helper.OLD_CALENDAR,
            "retry_delay": "30min",
            "retry_window": "6h",
            "max_attempts": 3,
            "timeout_start": "50min",
            "runner_timeout_seconds": 2700,
        },
        "unit_sha256": dict(helper.OLD_UNIT_HASHES),
        "shadow_evidence_root": "/home/andris/hermes-deals-shadow-evidence/edeka",
        "monitor_evidence_root": "/home/andris/hermes-deals-edeka-weekly-monitor",
        "cache_root": "/home/andris/.cache/hermes-deals-edeka-shadow",
        "unit_dir": str(cutover.UNIT_ROOT),
        "registration_scope": "unit_files_only_no_manager_reload",
    }
    for name in helper.FALSE_REGISTRATION_FLAGS:
        old_reg[name] = False
    assert helper.digest(helper.canonical_json(old_reg)) == helper.OLD_FINGERPRINT
    old_reg["registration_fingerprint_sha256"] = helper.OLD_FINGERPRINT

    old_ctl = {
        "schema_version": 1,
        "control": "edeka-weekly-monitor-control-v1",
        "issue_number": 26,
        "control_sha": helper.OLD_CONTROL_SHA,
        "dispatcher_blob": helper.OLD_DISPATCHER_BLOB,
        "dispatcher_sha256": helper.OLD_DISPATCHER_SHA256,
        "registration_sha": helper.OLD_SOURCE,
        "registration_fingerprint_sha256": helper.OLD_FINGERPRINT,
        "root_registration_only": True,
    }
    for name in helper.FALSE_CONTROL_FLAGS:
        old_ctl[name] = False

    dispatcher_old = b"synthetic-old-dispatcher"
    sudoers_old = cutover.sudoers_bytes(helper.OLD_CONTROL_SHA, helper.OLD_FINGERPRINT)
    assert cutover.sha256(sudoers_old) == helper.OLD_SUDOERS_SHA256
    helper.OLD_DISPATCHER_SHA256 = helper.digest(dispatcher_old)
    old_ctl["dispatcher_sha256"] = helper.OLD_DISPATCHER_SHA256
    old_units = {name: (tmp_path / "old" / name).read_bytes()
                 for name in helper.OLD_UNIT_HASHES}
    contents = {
        cutover.UNIT_ROOT / cutover.SERVICE: old_units[cutover.SERVICE],
        cutover.UNIT_ROOT / cutover.TIMER: old_units[cutover.TIMER],
        cutover.UNIT_ROOT / cutover.ALERT: old_units[cutover.ALERT],
        cutover.REG_PATH: cutover.json_bytes(old_reg),
        cutover.CTL_PATH: cutover.json_bytes(old_ctl),
        cutover.DISPATCHER_PATH: dispatcher_old,
        cutover.SUDOERS_PATH: sudoers_old,
    }
    helper.read_root_regular = lambda path, mode: contents[path]
    helper.read_json = lambda raw, expected_sha, label: json.loads(raw)
    return cutover, helper, contents


def test_pure_forward_bundle_has_only_six_exact_installed_file_updates(tmp_path: Path) -> None:
    cutover, helper, old = setup_old_state(tmp_path)
    control_sha = "1" * 40
    new_dispatcher = DISPATCHER.read_bytes()
    blob = cutover.git_blob_sha(new_dispatcher)
    original = deepcopy(old)
    new = cutover.build_candidates(helper, control_sha, new_dispatcher, blob)

    assert old == original, "pure source calculation must never mutate host input"
    assert set(new) == {
        cutover.UNIT_ROOT / cutover.SERVICE,
        cutover.UNIT_ROOT / cutover.TIMER,
        cutover.REG_PATH,
        cutover.CTL_PATH,
        cutover.DISPATCHER_PATH,
        cutover.SUDOERS_PATH,
    }
    assert cutover.sha256(new[cutover.UNIT_ROOT / cutover.SERVICE][0]) == cutover.EXPECTED_NEW_SERVICE_SHA256
    assert cutover.sha256(new[cutover.UNIT_ROOT / cutover.TIMER][0]) == cutover.EXPECTED_NEW_TIMER_SHA256
    assert cutover.sha256(new[cutover.REG_PATH][0]) == cutover.EXPECTED_NEW_REG_SHA256
    assert new[cutover.UNIT_ROOT / cutover.SERVICE][1] == 0o644
    assert new[cutover.REG_PATH][1] == 0o600
    assert new[cutover.DISPATCHER_PATH][1] == 0o755
    assert new[cutover.SUDOERS_PATH][1] == 0o440
    assert all(cutover.UNIT_ROOT / cutover.ALERT != p for p in new)

    registration = json.loads(new[cutover.REG_PATH][0])
    control = json.loads(new[cutover.CTL_PATH][0])
    assert registration["registration_fingerprint_sha256"] == cutover.EXPECTED_NEW_FP
    assert registration["registration_sha"] == cutover.APP_SOURCE
    assert registration["schedule"]["on_calendar"] == helper.NEW_CALENDAR
    assert control["control_sha"] == control_sha
    assert control["registration_sha"] == cutover.APP_SOURCE
    assert control["registration_fingerprint_sha256"] == cutover.EXPECTED_NEW_FP
    assert control["dispatcher_blob"] == blob
    assert control["dispatcher_sha256"] == cutover.sha256(new_dispatcher)
    sudoers = new[cutover.SUDOERS_PATH][0]
    assert sudoers.count(b"\n") == 3
    assert control_sha.encode() in sudoers
    assert helper.OLD_CONTROL_SHA.encode() not in sudoers
    assert all(registration[k] is False for k in helper.FALSE_REGISTRATION_FLAGS)
    assert all(control[k] is False for k in helper.FALSE_CONTROL_FLAGS)


@pytest.mark.parametrize(
    "observed,last_trigger,good",
    [
        ("2026-11-15T12:00:00+01:00", "Sun 2026-11-15 00:10:00 CET", True),
        ("2026-11-15T01:00:00+01:00", "Sun 2026-11-15 00:10:00 CET", False),
        ("2026-11-15T23:45:00+01:00", "Sun 2026-11-15 00:10:00 CET", False),
        ("2026-11-16T00:02:00+01:00", "Sun 2026-11-15 00:10:00 CET", False),
        ("2026-11-15T12:00:00+01:00", "Sun 2026-11-08 00:10:00 CET", False),
        ("2026-11-15T12:00:00+01:00", "Mon 2026-11-09 00:10:00 CET", False),
        ("2026-11-15T12:00:00+01:00", "", False),
    ],
)
def test_no_catchup_window_exact_sunday_only(observed: str, last_trigger: str,
                                             good: bool) -> None:
    cutover = module(CUTOVER, "edeka_forward_window")
    now = datetime.fromisoformat(observed)
    if good:
        cutover.require_sunday_no_catchup_window(now, last_trigger)
    else:
        with pytest.raises(cutover.StopCutover):
            cutover.require_sunday_no_catchup_window(now, last_trigger)


def test_persistent_timer_stamp_is_exact_sunday_and_never_modified(monkeypatch) -> None:
    cutover = module(CUTOVER, "edeka_forward_persistent_stamp")
    now = datetime.fromisoformat("2026-11-15T12:00:00+01:00")
    stamp = datetime.fromisoformat("2026-11-15T00:10:00+01:00")
    mtime = stamp.timestamp()
    details = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o644, st_uid=0, st_gid=0,
        st_size=0, st_mtime=mtime, st_mtime_ns=int(mtime * 1_000_000_000),
    )

    class FakeStamp:
        def __init__(self, snapshot) -> None:
            self.snapshot = snapshot

        def lstat(self):
            return self.snapshot

        def is_symlink(self):
            return False

    fake = FakeStamp(details)
    monkeypatch.setattr(cutover, "PERSISTENT_STAMP", fake)
    assert cutover.verify_persistent_stamp(now) == details.st_mtime_ns
    for changed in (
        SimpleNamespace(**{**vars(details), "st_mtime": mtime - 86400}),
        SimpleNamespace(**{**vars(details), "st_mode": stat.S_IFREG | 0o666}),
        SimpleNamespace(**{**vars(details), "st_size": 1}),
        SimpleNamespace(**{**vars(details), "st_uid": 1000}),
    ):
        fake.snapshot = changed
        with pytest.raises(cutover.StopCutover):
            cutover.verify_persistent_stamp(now)
    assert cutover.PERSISTENT_STAMP is fake


def test_readonly_mode_has_no_host_mutation_authority() -> None:
    src = CUTOVER.read_text(encoding="utf-8")
    assert 'choices=("preflight", "apply")' in src
    assert 'args.live_intent == "FORBIDDEN"' in src
    assert 'token == LIVE_TOKEN' in src
    assert 'run(["/usr/bin/systemctl", "reset-failed"' not in src
    assert 'os.unlink(' not in src
    assert 'shutil.rmtree(' not in src
    assert 'rollback(' not in src
    assert "GIT_OPTIONAL_LOCKS=" in src
    assert "LOCK_EX | fcntl.LOCK_NB" in src
    assert 'if args.phase == "preflight":' in src
