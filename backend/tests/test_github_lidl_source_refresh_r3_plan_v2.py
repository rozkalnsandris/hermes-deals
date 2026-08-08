from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-source-refresh-r3-plan-v2.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_r3_v2_workflow_is_owner_only_and_github_hosted() -> None:
    text = workflow_text()
    assert "issue_comment:" in text
    assert "github.event.issue.number == 361" in text
    assert "github.actor == 'rozkalnsandris'" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "command sender numeric ID is not allowlisted" in text
    assert r"/hermes-lidl-source-refresh-r3-plan-v2 artifact=([1-9][0-9]*)" in text
    assert "artifact_id != 9021545332" in text
    assert "runs-on: ubuntu-24.04" in text
    assert "self-hosted" not in text
    assert "sudo " not in text
    assert "pull_request_target" not in text
    assert "repository_dispatch" not in text


def test_r3_v2_workflow_uses_latest_pinned_github_actions() -> None:
    text = workflow_text()
    assert (
        "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2"
        in text
    )
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
        in text
    )
    assert "actions/checkout@v" not in text
    assert "actions/upload-artifact@v" not in text


def test_r3_v2_workflow_pins_exact_r2_artifact_and_runtime() -> None:
    text = workflow_text()
    assert "actions: read" in text
    assert "ref: ${{ needs.authorize.outputs.runtime_sha }}" in text
    assert "persist-credentials: false" in text
    assert "actions/artifacts/${ARTIFACT_ID}" in text
    assert "actions/artifacts/${ARTIFACT_ID}/zip" in text
    assert "lidl-source-refresh-r2-31256539018-1" in text
    assert "sha256:d4f9be1a19592a45739e4cc6a2827833682460e1c41bdd6496e0375077ef33c4" in text
    assert "workflow.get('id') != 31256539018" in text
    assert "workflow.get('head_branch') != 'main'" in text
    assert "workflow.get('head_sha') != '433fe078d042eac28862d84b7422f345144af962'" in text
    assert "workflow.get('repository_id') != 1317143994" in text


def test_r3_v2_workflow_is_strictly_plan_only() -> None:
    text = workflow_text()
    assert "python3 tools/lidl_source_refresh_r3_plan_v2.py" in text
    assert "R3_PLAN_READY" in text
    assert "WAIT_PROFILE" in text
    assert "fresh_owner_r3_promotion_authorization_required" in text
    assert "authorization_must_bind_plan_fingerprint" in text
    assert "exclusive_create_only" in text
    assert "overwrite_immutable_source_forbidden" in text
    assert "No R3 corpus/source-review/scan/authority promotion" in text
    assert "lidl_gate_b_family_promotion.py" not in text
    assert "lidl_gate_b_freeze_apply.py" not in text
