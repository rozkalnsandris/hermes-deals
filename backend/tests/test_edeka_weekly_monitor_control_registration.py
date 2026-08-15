from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = ROOT / "tools" / "runner" / "install_edeka_weekly_monitor_control_nonrewind.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "hermes-edeka-weekly-monitor-control.yml"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sudoers_is_exact_fingerprint_and_authority_bound() -> None:
    module = load_module(INSTALLER_PATH, "edeka_monitor_control_installer")
    payload = module.build_sudoers("1" * 40, module.EXPECTED_REGISTRATION_FINGERPRINT).decode()
    assert payload.count("\n") == 3
    assert " activate " in payload
    assert " disable " in payload
    assert " rollback " in payload
    assert "source-refetch=authorized bounded-retries=authorized" in payload
    assert payload.count("source-refetch=forbidden bounded-retries=forbidden") == 2
    assert module.EXPECTED_REGISTRATION_FINGERPRINT in payload


def test_repository_source_does_not_contain_contiguous_sudo_password_tag() -> None:
    source = INSTALLER_PATH.read_text(encoding="utf-8")
    assert "NOPASSWD" not in source
    assert "password" not in source.lower()


def test_control_registration_does_not_call_systemctl() -> None:
    source = INSTALLER_PATH.read_text(encoding="utf-8")
    assert "/usr/bin/systemctl" not in source
    assert '"systemd_change_performed": False' in source
    assert '"timer_enable_performed": False' in source
    assert '"timer_start_performed": False' in source


def test_control_registration_keeps_monitor_checkout_pinned() -> None:
    source = INSTALLER_PATH.read_text(encoding="utf-8")
    assert 'git_text("rev-parse", "HEAD") == EXPECTED_REGISTRATION_SHA' in source
    assert "HEAD must remain pinned to registration SHA" in source
    assert 'git_text("rev-parse", "refs/remotes/origin/main") == control_sha' in source


def test_workflow_has_no_write_permissions_and_fixed_dispatcher() -> None:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "permissions: {}" in source
    assert "issues: write" not in source
    assert "contents: write" not in source
    assert "actions: write" not in source
    assert "/usr/local/sbin/hermes-deals-edeka-weekly-monitor-control" in source
    assert "sudo --non-interactive --" in source
    assert "production_database_write_authorized" in source


def test_workflow_keeps_escape_hatches_independent_of_ci() -> None:
    author_source = (ROOT / "tools" / "github_edeka_weekly_monitor_control.py").read_text(encoding="utf-8")
    assert 'if command.operation == "activate":' in author_source
    assert 'ci_run_id = "not-required"' in author_source
