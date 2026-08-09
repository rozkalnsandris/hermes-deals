from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-heldout-review-pack.yml"


def test_review_pack_workflow_is_exact_upstream_and_owner_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit:netto-heldout-review-pack-v1" in text
    assert "pull_request_target:" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "actions: read" in text
    assert 'UPSTREAM_RUN_ID: "31324156565"' in text
    assert (
        "UPSTREAM_ARTIFACT: "
        "netto-heldout-github-c0701d76bfa6412cbf89b4bf9816a68ccb3c2ab8-run-31324156565"
    ) in text
    assert (
        "UPSTREAM_ARTIFACT_DIGEST: "
        "sha256:cc289165aaac8796b33391917edb03df1085a841b82d17fc08aa93efa1d66ec4"
    ) in text
    assert 'UPSTREAM_ARTIFACT_BYTES: "37892979"' in text
    assert "/actions/artifacts/{artifact['id']}/zip" in text
    assert "actions/download-artifact@" not in text
    assert "NoRedirect" in text


def test_review_pack_workflow_pins_exact_frozen_hz33_identity() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "UPSTREAM_COMMIT: c0701d76bfa6412cbf89b4bf9816a68ccb3c2ab8" in text
    assert "EXPECTED_CAMPAIGN: hz33_hasb" in text
    assert 'EXPECTED_VALID_FROM: "2026-08-10"' in text
    assert 'EXPECTED_VALID_UNTIL: "2026-08-15"' in text
    assert (
        "EXPECTED_SOURCE_SHA256: "
        "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb"
    ) in text
    assert (
        "EXPECTED_PDF_SHA256: "
        "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba"
    ) in text
    assert (
        "EXPECTED_FREEZE_MANIFEST_SHA256: "
        "38bb9445ad5f2c3cc0159bd4332a4138f1d81cab03591de0542825b3f88db087"
    ) in text
    assert 'EXPECTED_PAGE_COUNT: "77"' in text


def test_review_pack_workflow_extracts_only_reviewer_safe_source_members() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Extract only reviewer-safe source members" in text
    assert "if len(infos) != 15:" in text
    assert "if actual != allowed:" in text
    assert "SAFE_SOURCE_MEMBER_COUNT=" in text
    assert "github-capture-result.json" in text
    assert "live-source.json" in text
    assert "selected-binding.json" in text
    assert "capture/freeze-manifest.json" in text
    assert "capture/freeze-receipt.json" in text
    assert "capture/blind-review-template.json" in text
    assert (
        "source/netto/5659-hz33_hasb-"
        "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba.pdf"
    ) in text
    assert "capture_root=$safe_root" in text
    for forbidden in (
        "predictions.json",
        "predictions_sha256",
        "capture/source-evidence.json",
    ):
        assert forbidden not in text


def test_review_pack_workflow_never_exposes_predictions_or_production_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Parser predictions included: **false**" in text
    assert "Expected truth included: **false**" in text
    assert "Production deployment: **not authorized**" in text
    assert "Database/Review writes: **not authorized**" in text
    assert "persist-credentials: false" in text
    assert "actions/upload-artifact@v6" in text
    assert "artifact-id" in text
    assert "artifact-digest" in text
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "latest artifact",
    ):
        assert forbidden not in text
