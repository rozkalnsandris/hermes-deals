from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "tools/aldi_gate_d1_evidence_discovery_overlay_v2.py"
DISPATCH = ROOT / "tools/runner/aldi_gate_d1_evidence_discovery_overlay_dispatch_v2.py"
INSTALLER = ROOT / "tools/runner/install-aldi-gate-d1-evidence-discovery-overlay-v2.py"
WORKFLOW = ROOT / ".github/workflows/aldi-gate-d1-evidence-discovery-overlay-v2.yml"


def test_overlay_binds_immutable_v1_bundle_and_decoded_gate_b_identity() -> None:
    overlay = OVERLAY.read_text(encoding="utf-8")
    dispatch = DISPATCH.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "3188821faa36a6d9fb598fde521a59993e6cb11678a8160e4afead4ba4fcfdd4" in overlay
    assert "load_gate_b_authoritative(gate_b_plan)" in overlay
    assert "v1.EXPECTED_GATE_B_PLAN_SHA256 = raw_transport_sha" in overlay
    assert 'result["identity"]["gate_b_plan_sha256"] = CANONICAL_GATE_B_SHA256' in overlay
    assert "690a0a09364b59e323230d24af006542bbdb1012" in dispatch
    assert "481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f" in dispatch
    assert "481bd9ea014afb928f9f2b4b5d5f84c6f571c72c2524d7b442b16124ca73169f" in installer


def test_overlay_failure_export_is_sanitized_and_authority_closed() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (OVERLAY, DISPATCH, INSTALLER, WORKFLOW)
    )
    assert "raw_exception_exported" in combined
    assert "raw_evidence_exported" in combined
    assert "production_apply_authorized" in combined
    assert "review_pack_execution_authorized" in combined
    assert "discovery-failure.json" in combined
    assert "discovery.stderr" not in combined
    assert "set -euo pipefail" not in combined
    assert "set -Eeuo pipefail" not in combined


def test_overlay_installer_git_verification_is_read_only() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "GIT_OPTIONAL_LOCKS=0" in text
    assert 'audit_git("branch", "--show-current")' in text
    assert 'audit_git("rev-parse", "HEAD")' in text
    assert 'audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all")' in text
    for forbidden in ("checkout", "switch", "reset", "stash", "clean", "fetch", "pull", "merge", "rebase"):
        assert f'audit_git("{forbidden}"' not in text


def test_overlay_workflow_is_manual_and_rpi5_has_no_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    rpi5 = text.split("\n  rpi5:", 1)[1].split("\n  report:", 1)[0]
    assert "actions/checkout" not in rpi5
    assert "hermes-deals-audit" in rpi5
    assert "overlay-v2" in rpi5
