from __future__ import annotations

from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/origin-monitor-install-disabled.yml"
BOOTSTRAP = ROOT / "tools/runner/bootstrap-origin-monitor-control.sh"
CONTROL = ROOT / "tools/runner/origin-monitor-control.sh"
RUNNER = ROOT / "tools/runner/origin-monitor-run.sh"
SERVICE = ROOT / "deploy/systemd/hermes-deals-origin-monitor.service"
TIMER = ROOT / "deploy/systemd/hermes-deals-origin-monitor.timer"
RUNBOOK = ROOT / "docs/operations/origin-monitor-install-disabled.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_is_manual_only_and_has_no_activation_mode() -> None:
    text = read(WORKFLOW)
    parsed = yaml.safe_load(text)
    assert "workflow_dispatch" in parsed[True]
    assert "schedule" not in parsed[True]
    assert "enable" not in text
    assert "start" not in text
    assert "preflight" in text
    assert "install-disabled" in text
    assert "INSTALL DISABLED origin-monitor" in text


def test_workflow_owner_and_exact_blob_authorization_is_fail_closed() -> None:
    text = read(WORKFLOW)
    for marker in (
        'sender.get("login") != "rozkalnsandris"',
        "int(sender.get(\"id\") or 0) != 277435981",
        "package PR is not merged into main",
        "registered SHA is not reachable from current main",
        "registered package files differ from current main",
        "/usr/local/sbin/hermes-deals-origin-monitor-control",
        "actions/upload-artifact@v6",
    ):
        assert marker in text
    assert "actions/checkout@" not in text


def test_bootstrap_refuses_primary_worktree_and_does_not_touch_systemd() -> None:
    text = read(BOOTSTRAP)
    for marker in (
        "/home/andris/hermes-deals",
        "primary production worktree is forbidden",
        "source worktree must be detached",
        "source worktree is not clean",
        "merge-base --is-ancestor",
        "python3 -m py_compile",
        "visudo -cf",
        "MONITOR_RUNTIME_INSTALLED=false",
        "MONITOR_ENABLED=false",
        "MONITOR_EXECUTED=false",
    ):
        assert marker in text
    assert "systemctl" not in text


def test_control_allows_only_preflight_or_install_disabled() -> None:
    text = read(CONTROL)
    assert '"preflight" || "$mode" == "install-disabled"' in text
    assert "systemctl daemon-reload" in text
    assert "systemctl enable" not in text
    assert "systemctl start" not in text
    assert "systemctl restart" not in text
    assert "monitor_executed\":false" in text
    assert "production_deploy\":false" in text
    assert "database_read_write\":false" in text


def test_control_refuses_existing_active_or_enabled_monitor() -> None:
    text = read(CONTROL)
    assert '[[ "$active" != "active" && "$timer_active" != "active" ]]' in text
    assert '[[ "$enabled" != "enabled" && "$timer_enabled" != "enabled" ]]' in text
    assert "sha256sum --check --strict" in text


def test_runtime_has_fixed_endpoints_policy_permissions_and_retention() -> None:
    text = read(RUNNER)
    for marker in (
        'PUBLIC_URL="https://deals.rozkalns.net"',
        'ORIGIN_URL="http://192.168.0.180:9128"',
        'ORIGIN_HOST="deals.rozkalns.net"',
        "WINDOW_SIZE=5",
        "MIN_SAMPLES=3",
        "ALERT_THRESHOLD=3",
        "RETENTION_COUNT=20",
        "install -d -m 0700",
        "chmod 0600",
        "--timeout 5",
    ):
        assert marker in text
    assert "curl " not in text
    assert "journalctl" not in text
    assert "docker " not in text
    assert "psql " not in text


def test_systemd_units_are_hardened_but_not_self_activating() -> None:
    service = read(SERVICE)
    timer = read(TIMER)
    for marker in (
        "User=andris",
        "UMask=0077",
        "StateDirectoryMode=0700",
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "SuccessExitStatus=1 2",
    ):
        assert marker in service
    assert "OnUnitActiveSec=5min" in timer
    assert "Persistent=false" in timer
    assert "ExecStart" not in timer


def test_runbook_keeps_activation_separate() -> None:
    text = read(RUNBOOK)
    assert "does not contact the RPi5" in text
    assert "installed disabled" in text
    assert "Activation remains blocked" in text
    assert "separate issue, PR, CI and explicit owner authorization" in text


def test_shell_scripts_parse() -> None:
    for path in (BOOTSTRAP, CONTROL, RUNNER):
        subprocess.run(["bash", "-n", str(path)], check=True)
