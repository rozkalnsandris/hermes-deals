from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "edeka_weekly_monitor_control.py"
INSTALLER = ROOT / "tools" / "runner" / "install_edeka_weekly_monitor_control_nonrewind.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_config(module, sha: str = "b" * 40) -> dict:
    core = {
        "schema_version": 1,
        "registration_sha": sha,
        "repo_root": module.EXPECTED_REPO_ROOT,
        "planner_blob": module.EXPECTED_PLANNER_BLOB,
        "runtime_blob": module.EXPECTED_RUNTIME_BLOB,
        "installer_blob": module.EXPECTED_UNIT_REGISTRATION_INSTALLER_BLOB,
        "schedule": {
            "on_calendar": "Mon *-*-* 06:15:00 Europe/Berlin",
            "retry_delay": "30min",
            "retry_window": "6h",
            "max_attempts": 3,
            "timeout_start": "50min",
            "runner_timeout_seconds": 2700,
        },
        "unit_sha256": {module.SERVICE_UNIT: "1" * 64, module.TIMER_UNIT: "2" * 64, module.ALERT_UNIT: "3" * 64},
        "shadow_evidence_root": module.EXPECTED_SHADOW_EVIDENCE_ROOT,
        "monitor_evidence_root": module.EXPECTED_MONITOR_EVIDENCE_ROOT,
        "cache_root": module.EXPECTED_CACHE_ROOT,
        "unit_dir": str(module.UNIT_DIR),
        "registration_scope": "unit_files_only_no_manager_reload",
        "daemon_reload_performed": False,
        "timer_enable_performed": False,
        "timer_start_performed": False,
        "source_refetch_performed": False,
        "production_database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "production_deploy_performed": False,
    }
    return {**core, "registration_fingerprint_sha256": module.sha_bytes(module.canonical_bytes(core))}


def test_registration_config_fingerprint_and_exact_source_blobs_are_enforced() -> None:
    module = load(DISPATCHER, "edeka_monitor_control_config")
    config = safe_config(module)
    module.validate_registration_config(config, "b" * 40, config["registration_fingerprint_sha256"])
    config["runtime_blob"] = "f" * 40
    with pytest.raises(module.ControlError, match="runtime blob"):
        module.validate_registration_config(config, "b" * 40, config["registration_fingerprint_sha256"])


def test_activate_requires_literal_refetch_and_retry_authority_tokens() -> None:
    module = load(DISPATCHER, "edeka_monitor_control_args")
    fp = "a" * 64
    sha = "b" * 40
    assert module.parse_argv(["activate", sha, fp, "source-refetch-authorized", "bounded-retries-authorized"]) == ("activate", sha, fp, True, True)
    for bad in (
        ["activate", sha, fp],
        ["activate", sha, fp, "source-refetch-authorized", "retries-no"],
        ["activate", sha, fp, "source-refetch-authorized", "bounded-retries-authorized", "extra"],
    ):
        with pytest.raises(module.ControlError):
            module.parse_argv(bad)


def test_activate_uses_explicit_reload_enable_no_reload_then_start(monkeypatch) -> None:
    module = load(DISPATCHER, "edeka_monitor_control_activate")
    calls: list[list[str]] = []
    state = {"enabled": False, "active": False, "service": False}
    monkeypatch.setattr(module, "validate_exact_source_checkout", lambda _sha: None)
    monkeypatch.setattr(module, "timer_is_live_enabled", lambda: state["enabled"])
    monkeypatch.setattr(module, "timer_is_active", lambda: state["active"])
    monkeypatch.setattr(module, "service_is_active", lambda: state["service"])
    def fake_run(argv, *, check=True, timeout=120):
        calls.append(list(argv))
        if argv[:3] == ["/usr/bin/systemctl", "enable", "--no-reload"]:
            state["enabled"] = True
        if argv[:2] == ["/usr/bin/systemctl", "start"]:
            state["active"] = True
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()
    monkeypatch.setattr(module, "run_command", fake_run)
    detail = module.activate({}, "b" * 40)
    assert calls[:3] == [
        ["/usr/bin/systemctl", "daemon-reload"],
        ["/usr/bin/systemctl", "enable", "--no-reload", module.TIMER_UNIT],
        ["/usr/bin/systemctl", "start", module.TIMER_UNIT],
    ]
    assert detail["timer_may_trigger_refetch"] is True
    assert detail["root_host_mutation_performed"] is True


def test_activate_blocks_unexpected_running_service_before_mutation(monkeypatch) -> None:
    module = load(DISPATCHER, "edeka_monitor_control_service_preflight")
    monkeypatch.setattr(module, "validate_exact_source_checkout", lambda _sha: None)
    monkeypatch.setattr(module, "timer_is_live_enabled", lambda: False)
    monkeypatch.setattr(module, "timer_is_active", lambda: False)
    monkeypatch.setattr(module, "service_is_active", lambda: True)
    monkeypatch.setattr(module, "run_command", lambda *args, **kwargs: pytest.fail("systemd mutation must not run"))
    with pytest.raises(module.ControlError, match="unexpectedly active"):
        module.activate({}, "b" * 40)


def test_failed_activation_restores_disabled_inactive_state(monkeypatch) -> None:
    module = load(DISPATCHER, "edeka_monitor_control_cleanup")
    state = {"enabled": False, "active": False, "service": False}
    monkeypatch.setattr(module, "validate_exact_source_checkout", lambda _sha: None)
    monkeypatch.setattr(module, "timer_is_live_enabled", lambda: state["enabled"])
    monkeypatch.setattr(module, "timer_is_active", lambda: state["active"])
    monkeypatch.setattr(module, "service_is_active", lambda: state["service"])
    def fake_run(argv, *, check=True, timeout=120):
        if argv[:3] == ["/usr/bin/systemctl", "enable", "--no-reload"]:
            state["enabled"] = True
        elif argv[:2] == ["/usr/bin/systemctl", "start"]:
            state["active"] = True
            raise module.ControlError("simulated timer start verification failure")
        elif argv[:2] == ["/usr/bin/systemctl", "stop"] and argv[-1] == module.TIMER_UNIT:
            state["active"] = False
        elif argv[:2] == ["/usr/bin/systemctl", "stop"] and argv[-1] == module.SERVICE_UNIT:
            state["service"] = False
        elif argv[:3] == ["/usr/bin/systemctl", "disable", "--no-reload"]:
            state["enabled"] = False
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()
    monkeypatch.setattr(module, "run_command", fake_run)
    with pytest.raises(module.ControlError, match="simulated"):
        module.activate({}, "b" * 40)
    assert state == {"enabled": False, "active": False, "service": False}


def test_disable_and_rollback_source_preserve_evidence_roots_and_recheck_config_bytes() -> None:
    source = DISPATCHER.read_text(encoding="utf-8")
    assert '["/usr/bin/systemctl", "disable", "--no-reload", TIMER_UNIT]' in source
    assert '["/usr/bin/systemctl", "stop", TIMER_UNIT]' in source
    assert '["/usr/bin/systemctl", "stop", SERVICE_UNIT]' in source
    assert "EXPECTED_SHADOW_EVIDENCE_ROOT" in source
    assert "EXPECTED_MONITOR_EVIDENCE_ROOT" in source
    assert "EXPECTED_CACHE_ROOT" in source
    assert "expected_config_sha256 = sha_bytes(canonical_bytes(config))" in source
    assert "_unlink_verified(CONFIG, mode=0o600, expected_sha256=expected_config_sha256)" in source
    assert "rmtree" not in source
    assert "unlink()" in source


def test_control_registration_sudoers_is_shape_bounded_and_nonactivating() -> None:
    installer = load(INSTALLER, "edeka_monitor_control_registration")
    sudoers = installer.build_sudoers().decode("utf-8")
    assert "source-refetch-authorized bounded-retries-authorized" in sudoers
    assert "activate [0-9a-f]{40} [0-9a-f]{64}" in sudoers
    assert "disable [0-9a-f]{40} [0-9a-f]{64}" in sudoers
    assert "rollback [0-9a-f]{40} [0-9a-f]{64}" in sudoers
    assert "NOPASSWD:" in sudoers
    source = INSTALLER.read_text(encoding="utf-8")
    assert "daemon-reload" not in source
    assert '"/usr/bin/systemctl"' not in source
    assert '"systemd_change_performed": False' in source
    assert '"timer_activation_performed": False' in source
    assert '"source_refetch_authorized": False' in source
    assert '"bounded_retry_authorized": False' in source


def test_control_registration_pins_dispatcher_and_unit_registration_blobs() -> None:
    installer = load(INSTALLER, "edeka_monitor_control_pins")
    assert installer.EXPECTED_DISPATCHER_BLOB == "39e8aa18c6fdc5e27f0dd248602ba5fd97954ea4"
    assert installer.EXPECTED_UNIT_INSTALLER_BLOB == "91ddc076ec6407b567a3ae3300bef0e8a7adfca5"
    source = INSTALLER.read_text(encoding="utf-8")
    assert 'git_text("rev-parse", "refs/remotes/origin/main") == registration_sha' in source
