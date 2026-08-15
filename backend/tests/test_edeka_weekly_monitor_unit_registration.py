from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools" / "runner" / "install_edeka_weekly_monitor_units_nonactivating.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("edeka_monitor_unit_registration", INSTALLER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_plan(module, tmp_path: Path, sha: str = "a" * 40):
    unit_hashes = {}
    for index, name in enumerate(module.UNIT_NAMES, start=1):
        path = tmp_path / name
        path.write_text(f"unit-{index}\n", encoding="utf-8")
        unit_hashes[name] = module.sha_file(path)
    return {
        "schema_version": 1,
        "planner_version": "edeka-weekly-monitor-activation-plan-v1",
        "repo_sha": sha,
        "schedule": {
            "on_calendar": "Mon *-*-* 06:15:00 Europe/Berlin",
            "persistent": True,
            "max_attempts_per_retry_window": 3,
            "retry_delay": "30min",
            "retry_window": "6h",
            "timeout_start": "50min",
            "runner_timeout_seconds": 2700,
        },
        "unit_sha256": unit_hashes,
        "activation_requires_explicit_owner_authorization": True,
        "preflight_before_mutation": True,
        "rollback_preserves_shadow_evidence_root": True,
        "rollback_preserves_monitor_evidence_root": True,
        "rollback_preserves_cache_root": True,
        "source_refetch_authorized": False,
        "systemd_change_authorized": False,
        "systemd_change_performed": False,
        "bounded_retry_authorized": False,
        "production_database_write_authorized": False,
        "review_write_authorized": False,
        "publication_authorized": False,
        "deployment_authorized": False,
    }, unit_hashes


def test_exact_safe_plan_is_accepted(tmp_path: Path) -> None:
    module = load_installer()
    plan, expected_hashes = safe_plan(module, tmp_path)
    hashes = module.validate_generated_plan(
        plan,
        registration_sha="a" * 40,
        on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="50min",
        runner_timeout_seconds=2700,
        output_dir=tmp_path,
    )
    assert hashes == expected_hashes


@pytest.mark.parametrize(
    "unsafe_key",
    [
        "source_refetch_authorized",
        "systemd_change_authorized",
        "systemd_change_performed",
        "bounded_retry_authorized",
        "production_database_write_authorized",
        "review_write_authorized",
        "publication_authorized",
        "deployment_authorized",
    ],
)
def test_plan_rejects_any_unsafe_authority_flag(tmp_path: Path, unsafe_key: str) -> None:
    module = load_installer()
    plan, _ = safe_plan(module, tmp_path)
    plan[unsafe_key] = True
    with pytest.raises(module.RegistrationError, match="unsafe generated monitor plan flag"):
        module.validate_generated_plan(
            plan,
            registration_sha="a" * 40,
            on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
            retry_delay="30min",
            retry_window="6h",
            max_attempts=3,
            timeout_start="50min",
            runner_timeout_seconds=2700,
            output_dir=tmp_path,
        )


def test_registration_config_is_deterministic_and_nonactivating() -> None:
    module = load_installer()
    blobs = {
        module.PLANNER_REL: module.EXPECTED_PLANNER_BLOB,
        module.RUNTIME_REL: module.EXPECTED_RUNTIME_BLOB,
        module.INSTALLER_REL: "b" * 40,
    }
    unit_hashes = {name: str(index) * 64 for index, name in enumerate(module.UNIT_NAMES, start=1)}
    kwargs = dict(
        registration_sha="c" * 40,
        blobs=blobs,
        on_calendar="Mon *-*-* 06:15:00 Europe/Berlin",
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="50min",
        runner_timeout_seconds=2700,
        unit_hashes=unit_hashes,
    )
    first = module.build_registration_config(**kwargs)
    second = module.build_registration_config(**kwargs)
    assert first == second
    assert len(first["registration_fingerprint_sha256"]) == 64
    assert first["daemon_reload_performed"] is False
    assert first["timer_enable_performed"] is False
    assert first["timer_start_performed"] is False
    assert first["source_refetch_performed"] is False
    assert first["production_database_write_performed"] is False
    assert first["production_deploy_performed"] is False


def test_exclusive_registration_refuses_unknown_existing_bytes(tmp_path: Path) -> None:
    module = load_installer()
    target = tmp_path / "unit.service"
    uid = os.getuid()
    gid = os.getgid()
    assert module.write_exclusive_or_identical(target, b"expected\n", 0o600, uid=uid, gid=gid) is True
    assert module.write_exclusive_or_identical(target, b"expected\n", 0o600, uid=uid, gid=gid) is False
    target.write_bytes(b"drift\n")
    os.chmod(target, 0o600)
    before = target.read_bytes()
    with pytest.raises(module.RegistrationError, match="content drift"):
        module.write_exclusive_or_identical(target, b"expected\n", 0o600, uid=uid, gid=gid)
    assert target.read_bytes() == before


def test_registration_source_has_no_systemd_mutation_command() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert '["/usr/bin/systemctl", "is-active", unit]' in source
    assert '["/usr/bin/systemctl", "is-enabled", TIMER_UNIT]' in source
    assert '"daemon-reload"' not in source
    assert '["/usr/bin/systemctl", "enable"' not in source
    assert '["/usr/bin/systemctl", "start"' not in source
    assert '["/usr/bin/systemctl", "restart"' not in source
    assert '"--now"' not in source


def test_registration_pins_the_merged_monitor_source_blobs() -> None:
    module = load_installer()
    assert module.EXPECTED_PLANNER_BLOB == "749f4d2ff09d50a9d53e45887013d6d4d79ed69a"
    assert module.EXPECTED_RUNTIME_BLOB == "4c863cf516a7de6cf8684b9b3ba3f1eb22785141"
    assert module.UNIT_NAMES == (
        "hermes-edeka-weekly-monitor.service",
        "hermes-edeka-weekly-monitor.timer",
        "hermes-edeka-weekly-monitor-failure@.service",
    )


def test_registration_input_rejects_schedule_injection() -> None:
    module = load_installer()
    with pytest.raises(module.RegistrationError, match="one line"):
        module.validate_inputs(
            "weekly\nExecStart=/bin/sh",
            "30min",
            "6h",
            3,
            "50min",
            2700,
        )
