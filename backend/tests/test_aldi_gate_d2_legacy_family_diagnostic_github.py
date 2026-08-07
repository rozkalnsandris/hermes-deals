from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/aldi-gate-d2-legacy-family-diagnostic-rpi5.yml"
INSTALLER = ROOT / "tools/runner/install-aldi-gate-d2-legacy-family-diagnostic.py"
DISPATCHER = ROOT / "tools/runner/aldi_gate_d2_legacy_family_diagnostic_dispatch.py"
DIAGNOSTIC = ROOT / "tools/aldi_gate_d2_legacy_family_diagnostic.py"


def test_workflow_is_owner_only_manual_rpi5_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert 'ACTOR"] != "rozkalnsandris"' in text
    assert 'ACTOR_ID"] != "277435981"' in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "actions/checkout" not in text
    assert "pr_number" in text


def test_new_execution_files_do_not_use_strict_shell_mode() -> None:
    for path in (WORKFLOW, INSTALLER, DISPATCHER, DIAGNOSTIC):
        text = path.read_text(encoding="utf-8")
        assert "set -euo pipefail" not in text
        assert "set -Eeuo pipefail" not in text


def test_installer_binds_frozen_v1_gate_d_bundle() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'V1_COMMIT = "690a0a09364b59e323230d24af006542bbdb1012"' in text
    assert 'V1_MANIFEST_SHA256 = "481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f"' in text
    assert 'FROZEN_GATE_D_RELATIVE = "tools/aldi_weekly_gate_d_visual_review_pack.py"' in text
    assert 'require("docker" not in groups' in text
    for forbidden in ("checkout", "switch", "reset", "stash", "clean", "pull", "fetch", "merge", "rebase"):
        assert f'audit_git("{forbidden}"' not in text


def test_dispatcher_exports_only_sanitized_diagnostic_files() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert 'copy_export(result_path, export_dir / "diagnostic-result.json")' in text
    assert 'copy_export(exit_path, export_dir / "diagnostic-exit-code.txt")' in text
    assert '"raw_evidence_exported": False' in text
    assert '"raw_exception_exported": False' in text
    assert '"production_apply_authorized": False' in text
    assert '"review_pack_execution_authorized": False' in text
    assert "shutil.copytree" not in text


def test_diagnostic_keeps_frozen_49_plus_41_contract() -> None:
    text = DIAGNOSTIC.read_text(encoding="utf-8")
    assert 'EXPECTED_PAGE_COUNTS = {"current": 49, "preview": 41}' in text
    assert '"strict_49_plus_41_frozen_contract_unchanged": True' in text
    assert '"production_eligible": False' in text
    assert '"review_pack_execution_authorized": False' in text
