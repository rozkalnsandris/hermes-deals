from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "aldi-gate-d3-recovery-inventory-rpi5.yml"
INSTALLER = ROOT / "tools" / "runner" / "install-aldi-gate-d3-recovery-inventory.py"
DISPATCHER = ROOT / "tools" / "runner" / "aldi_gate_d3_recovery_inventory_dispatch.py"


def test_gate_d3_workflow_is_manual_owner_only_and_sanitized():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "actions/checkout" not in text
    assert "hermes-deals-aldi-gate-d3-recovery-inventory" in text
    assert "Raw page images exported: **false**" in text
    assert "Archive extraction: **false / not authorized**" in text
    assert "Production DB/deploy: **false / not authorized**" in text


def test_gate_d3_installer_preserves_exact_sha_audit_boundary():
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'require(audit_git("branch", "--show-current").decode().strip() == "main"' in text
    assert 'require(audit_git("rev-parse", "HEAD").decode().strip() == commit_sha' in text
    assert '"status", "--porcelain=v1", "-z", "--untracked-files=all"' in text
    assert 'require("docker" not in groups' in text
    assert '"archive_extraction_authorized": False' in text
    assert '"production_apply_authorized": False' in text


def test_gate_d3_dispatcher_exports_only_sanitized_inventory():
    text = DISPATCHER.read_text(encoding="utf-8")
    assert 'STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")' in text
    assert '"raw_evidence_exported": False' in text
    assert '"raw_exception_exported": False' in text
    assert '"archive_extraction_authorized": False' in text
    assert "shutil.copyfile(result, export / \"diagnostic-result.json\"" in text
    assert "extractall" not in text
    assert "tarfile" not in text
