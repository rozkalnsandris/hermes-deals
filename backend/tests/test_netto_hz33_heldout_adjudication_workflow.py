from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-heldout-adjudication.yml"


def test_workflow_is_owner_merged_pr_and_exact_capture_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-hz33-adjudication-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert 'CAPTURE_RUN_ID: "31324156565"' in text
    assert 'CAPTURE_ARTIFACT_ID: "9041052231"' in text
    assert "cc289165aaac8796b33391917edb03df1085a841b82d17fc08aa93efa1d66ec4" in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text
    assert "2972cc717bd7cb0156d766f80679c94d26123b2b" in text
    assert '"merged": pr.get("merged") is True' in text


def test_workflow_extracts_only_post_truth_adjudication_inputs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '"capture/predictions.json"' in text
    assert '"capture/freeze-manifest.json"' in text
    assert '"capture/freeze-receipt.json"' in text
    assert "source/netto" not in text
    assert "live-source.json" not in text
    assert "selected-binding.json" not in text
    assert "blind-review-template.json" not in text


def test_workflow_is_read_only_and_fails_closed_after_preserving_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "kubectl ",
    ):
        assert forbidden not in text
    assert "actions/upload-artifact@v4" in text
    assert "Fail closed when frozen acceptance does not pass" in text
    assert "exit 2" in text
    assert "Promotion ready: **false**" in text
    assert "Production deployment / DB / Review writes: **false**" in text


def test_workflow_uses_frozen_protocol_without_threshold_overrides() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--require-acceptance" not in text
    assert "minimum_auto_single_precision" not in text
    assert "minimum_mixed_source_cells" not in text
    assert "maximum_mixed_source_auto_single" not in text
    assert "maximum_excluded_control_auto_eligible" not in text
    assert "maximum_cross_cell_group_reuse" not in text
    assert "python tools/netto_heldout_hz33_adjudication.py" in text
