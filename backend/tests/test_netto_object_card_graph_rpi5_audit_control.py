from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-object-card-graph-rpi5-audit.yml"
INSTALLER = ROOT / "tools/runner/install-netto-object-card-graph-rpi5-audit.sh"

LABEL = "audit:netto-object-card-graph-v1"
WORKTREE = "/home/andris/hermes-deals-worktrees/netto-object-card-graph-audit-v1"
RUNTIME_ROOT = "/usr/local/libexec/hermes-deals-audits/netto-object-card-graph-audit-v1"
DISPATCHER = "/usr/local/sbin/hermes-deals-netto-object-card-graph-audit-dispatch"
CONFIG = "/etc/hermes-deals-audits.d/netto-object-card-graph-audit-v1.conf"
SUDOERS = "/etc/sudoers.d/hermes-deals-netto-object-card-graph-audit"
EXPECTED_N9_SHA = "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"


def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def installer() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_workflow_is_owner_gated_and_self_hosted_job_has_no_checkout() -> None:
    text = workflow()
    assert "pull_request_target:" in text
    assert LABEL in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "object-card graph audits are accepted only on merged pull requests" in text
    assert "exact merged SHA has no successful main-push Hermes Deals CI checks run" in text
    audit_job = text.split("  rpi5-audit:", 1)[1].split("  report:", 1)[0]
    assert "permissions: {}" in audit_job
    assert "actions/checkout" not in audit_job
    for runner_label in ("self-hosted", "Linux", "ARM64", "hermes-deals-audit"):
        assert f"- {runner_label}" in audit_job


def test_workflow_uses_only_dedicated_dispatcher_and_sanitized_artifact() -> None:
    text = workflow()
    audit_job = text.split("  rpi5-audit:", 1)[1].split("  report:", 1)[0]
    assert f"sudo --non-interactive {DISPATCHER}" in audit_job
    assert "netto-object-card-graph-v1-${{ needs.authorize.outputs.sha }}" in audit_job
    assert "Image binary retention: **false by contract**" in audit_job
    assert "OCR: **disabled by contract**" in audit_job
    assert "Production deployment: **not authorized**" in audit_job


def test_installer_is_shell_syntax_valid_and_pins_paths() -> None:
    text = installer()
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
    assert WORKTREE in text
    assert RUNTIME_ROOT in text
    assert DISPATCHER in text
    assert CONFIG in text
    assert SUDOERS in text
    assert EXPECTED_N9_SHA in text
    assert "PyMuPDF 1.28.0 required" in text
    assert "github-runner must not belong to the Docker group" in text


def test_installer_copies_exact_object_graph_dependency_chain() -> None:
    text = installer()
    for member in (
        "tools/netto_object_card_graph_audit.py",
        "tools/netto_card_region_topology_audit.py",
        "tools/netto_ownership_separator_audit.py",
        "tools/netto_visual_geometry_corpus_replay.py",
        "tools/netto_visual_geometry_shadow.py",
        "backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json",
    ):
        assert member in text
    for key in (
        "object_graph_tool_sha256",
        "topology_tool_sha256",
        "ownership_audit_tool_sha256",
        "base_replay_tool_sha256",
        "parser_tool_sha256",
        "ownership_truth_sha256",
        "n9_manifest_sha256",
    ):
        assert key in text


def test_dispatcher_executes_as_andris_and_validates_non_promotable_contract() -> None:
    text = installer()
    assert 'runuser -u andris -- /usr/bin/env -i' in text
    assert '/usr/bin/python3 "$object_graph_tool_path"' in text
    assert '--output "$STAGING_DIR/object-card-graph-audit.json"' in text
    for marker in (
        '"cell_count": payload.get("cell_count") == 100',
        '"image_binary_retained": payload.get("image_binary_retained") is False',
        '"ocr_used": payload.get("ocr_used") is False',
        '"classification_performed": payload.get("classification_performed") is False',
        '"parser_behavior_changed": payload.get("parser_behavior_changed") is False',
        '"review_only": payload.get("review_only") is True',
        '"promotion_ready": payload.get("promotion_ready") is False',
        '"database_write_performed": payload.get("database_write_performed") is False',
        '"deployment_performed": payload.get("deployment_performed") is False',
    ):
        assert marker in text


def test_installer_never_performs_production_or_service_mutations() -> None:
    text = installer()
    for forbidden in (
        "docker run",
        "docker compose",
        "systemctl ",
        "cloudflared ",
        "psql ",
        "alembic upgrade",
        "curl ",
    ):
        assert forbidden not in text
    assert 'echo "AUDIT_EXECUTED=false"' in text
    assert 'echo "DATABASE_WRITE=false"' in text
    assert 'echo "REVIEW_WRITE=false"' in text
    assert 'echo "APPROVAL_PUBLICATION=false"' in text
    assert 'echo "PRODUCTION_DEPLOY=false"' in text
