from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-disagreement-diagnostic.yml"


def test_workflow_is_owner_merged_pr_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-hz33-disagreement-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert '"merged": pr.get("merged") is True' in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text
    assert 'EXPECTED_CAPTURE_RUN_ID: "31324156565"' in text
    assert 'EXPECTED_CAPTURE_ARTIFACT_ID: "9041052231"' in text


def test_workflow_reads_only_committed_adjudication_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit/netto/hz33/heldout-adjudication.json" in text
    assert "audit/netto/hz33/heldout-adjudication-receipt.json" in text
    assert "python tools/netto_hz33_adjudication_diagnostic.py" in text
    assert "predictions.json" not in text
    assert "freeze-manifest.json" not in text
    assert "completed-source-truth.json.gz" not in text


def test_workflow_never_mutates_parser_or_production() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "kubectl ",
        "git push",
    ):
        assert forbidden not in text
    assert "actions/upload-artifact@v4" in text
    assert "Threshold tuning: **false**" in text
    assert "Parser behavior changed: **false**" in text
    assert "Review-only / promotion-ready: **true / false**" in text
