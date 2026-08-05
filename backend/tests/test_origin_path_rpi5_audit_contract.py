from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/origin-path-rpi5-audit.yml"
INSTALLER = ROOT / "tools/runner/install-origin-path-rpi5-audit.sh"
DISPATCHER = ROOT / "tools/runner/origin-path-rpi5-audit-dispatcher.sh"
DOC = ROOT / "docs/operations/origin-path-rpi5-audit.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_origin_path_workflow_is_manual_owner_authorized_and_checkout_free():
    text = read(WORKFLOW)

    assert "workflow_dispatch:" in text
    assert "ACTOR_ID: ${{ github.actor_id }}" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    assert "audit accepts only merged pull requests" in text
    assert "merged SHA is not reachable from current main" in text
    assert "as_of must be a valid YYYY-MM-DD date" in text
    assert "actions/checkout@" not in text
    assert "hermes-deals-rpi5-audit" in text
    assert "/usr/local/sbin/hermes-deals-origin-path-audit-dispatch" in text
    assert "actions/upload-artifact@v6" in text


def test_workflow_requires_the_exact_registered_files():
    text = read(WORKFLOW)

    for path in (
        "tools/hermes_deals_origin_probe.py",
        "tools/runner/install-origin-path-rpi5-audit.sh",
        "tools/runner/origin-path-rpi5-audit-dispatcher.sh",
        ".github/workflows/origin-path-rpi5-audit.yml",
        "docs/operations/origin-path-rpi5-audit.md",
    ):
        assert f'"{path}"' in text


def test_installer_is_detached_fail_closed_and_does_not_execute_the_audit():
    text = read(INSTALLER)

    assert "primary production worktree is forbidden" in text
    assert "source worktree must be detached" in text
    assert "source worktree is not clean" in text
    assert "merge-base --is-ancestor" in text
    assert "python3 -m py_compile" in text
    assert "bash -n" in text
    assert "visudo -cf" in text
    assert "WORKFLOW_EXECUTED=false" in text
    assert "systemctl" not in text
    assert "docker " not in text
    assert "alembic" not in text


def test_dispatcher_is_fixed_read_only_and_sanitizes_the_report():
    text = read(DISPATCHER)

    assert "runuser -u andris -- /usr/bin/env -i" in text
    assert "https://deals.rozkalns.net" in text
    assert "http://192.168.0.180:9128" in text
    assert "deals.rozkalns.net" in text
    assert "expected exactly six probes" in text
    assert "unsafe response header entered report" in text
    assert "unsafe problem field entered report" in text
    assert "PRODUCTION_DATABASE_WRITE=false" in text
    assert "PRODUCTION_DEPLOYMENT=false" in text
    assert "RESTART_OR_CONFIGURATION_MUTATION=false" in text
    for forbidden in (
        "journalctl",
        "systemctl",
        "docker ",
        "docker-compose",
        "alembic",
        "pg_dump",
        "psql ",
        "curl ",
        "wget ",
    ):
        assert forbidden not in text


def test_artifact_path_and_permissions_are_narrowly_bounded():
    text = read(DISPATCHER)

    assert "/home/github-runner/_work/_temp/hermes-deals-origin-path-audit-*" in text
    assert "github-runner:github-runner" in text
    assert "artifact directory permissions must be 0700" in text
    assert 'destination="$EXPORT_DIR/audit-evidence"' in text
    assert 'find "$destination" -type f -exec chmod 0600' in text


def test_shell_scripts_parse():
    for path in (INSTALLER, DISPATCHER):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_runbook_records_install_execute_evidence_and_remove_boundaries():
    text = read(DOC)

    assert "The self-hosted job performs no repository checkout" in text
    assert "The installer does not run the workflow or probe." in text
    assert "Raw response bodies" in text
    assert "sudo tools/runner/install-origin-path-rpi5-audit.sh --remove" in text
    assert "does not collect `journalctl`" in text
