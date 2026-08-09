from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-heldout-source-truth-ledger.yml"


def test_source_truth_workflow_is_exact_owner_gated_and_source_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit:netto-heldout-source-truth-v1" in text
    assert "pull_request_target:" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert 'UPSTREAM_RUN_ID: "31324981193"' in text
    assert "UPSTREAM_ARTIFACT: netto-heldout-review-pack-hz33-run-31324981193" in text
    assert (
        "UPSTREAM_ARTIFACT_DIGEST: "
        "sha256:5e3a80fd1187a557984d4a4e47530c7514723d31e82c0183caaf4498277f3cf6"
    ) in text
    assert (
        "EXPECTED_PACK_MANIFEST_SHA256: "
        "e47e1acc337f55dcdbbbfbbb5c200b3c100427ee5e022ad7d0e5e947e2f7274c"
    ) in text
    assert (
        "EXPECTED_OLD_BLANK_LEDGER_SHA256: "
        "bc7170d05f075bcd7d90d12952b5811b14a51e69da60304337fcb4aeec557f55"
    ) in text
    assert 'EXPECTED_PAGE_COUNT: "77"' in text
    assert "actions/download-artifact@v5" in text
    assert "actions/upload-artifact@v6" in text
    assert "persist-credentials: false" in text


def test_source_truth_workflow_never_crosses_prediction_or_production_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Parser predictions included: **false**" in text
    assert "Adjudication started: **false**" in text
    assert "Production deployment: **not authorized**" in text
    assert "Database/Review writes: **not authorized**" in text
    for forbidden in (
        "predictions.json",
        "predictions_sha256",
        "parser_identity",
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
    ):
        assert forbidden not in text
