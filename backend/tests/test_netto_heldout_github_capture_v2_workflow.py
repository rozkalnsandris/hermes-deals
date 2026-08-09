from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-heldout-github-capture-v2.yml"
LAUNCHER = ROOT / "tools/run-netto-heldout-github-capture-v02.sh"


def test_v2_workflow_is_owner_gated_non_root_and_uses_v2_launcher() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-heldout-github-v2" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "trigger PR is not merged into repository main" in text
    assert "compare/{sha}...main" in text
    assert "[self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert '[[ "$(id -un)" == "github-runner" ]]' in text
    assert '! id -nG | tr \' \' \'\\n\' | grep -Fxq docker' in text
    assert "persist-credentials: false" in text
    assert "run-netto-heldout-github-capture-v02.sh" in text
    assert "actions/upload-artifact@v6" in text
    assert "Candidate decisions frozen before truth" in text


def test_v2_workflow_never_crosses_production_or_privileged_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "sudo ",
        "docker ",
        "docker.sock",
        "psql ",
        "systemctl ",
        "/home/andris",
        "deploy-main",
        "DATABASE_URL=postgres",
    ):
        assert forbidden not in text


def test_v2_launcher_uses_v1_source_selection_but_v2_capture() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "netto_heldout_live_source.py" in text
    assert "netto_heldout_source_selector.py" in text
    assert "netto_heldout_page_capture_v2.py" in text
    assert "freeze-receipt.json" in text
    assert "freeze-receipt-v2.json" in text
    assert "candidate-provenance.json" in text
    assert "candidate_decisions_frozen_before_truth" in text
    assert 'DATABASE_WRITE=false' in text
    assert 'REVIEW_WRITE=false' in text
    assert 'PRODUCTION_DEPLOY=false' in text
    assert 'PROMOTION_READY=false' in text
