from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/netto-heldout-adjudication.yml"


def test_adjudication_workflow_is_exact_owner_gated_and_hash_bound() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "audit:netto-heldout-adjudication-v1",
        "pull_request_target:",
        'EXPECTED_OWNER_ID: "277435981"',
        'UPSTREAM_RUN_ID: "31324156565"',
        "netto-heldout-github-c0701d76bfa6412cbf89b4bf9816a68ccb3c2ab8-run-31324156565",
        "sha256:cc289165aaac8796b33391917edb03df1085a841b82d17fc08aa93efa1d66ec4",
        'UPSTREAM_ARTIFACT_BYTES: "37892979"',
        "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94",
        "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6",
        "capture/predictions.json",
        "capture/freeze-manifest.json",
        "capture/freeze-receipt.json",
        "capture/SHA256SUMS",
        "completed-independent-source-truth-ledger.json.gz.b64",
        "tools/netto_heldout_prediction_group_adjudication.py",
    ):
        assert required in text


def test_adjudication_workflow_does_not_bypass_frozen_artifact_or_production_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "actions/download-artifact",
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "deploy-main",
        "production_eligible=true is the only automatic",
        "hz31_hasb_4",
        "hz32_hasb",
    ):
        assert forbidden not in text


def test_adjudication_workflow_extracts_only_bounded_frozen_members() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'if len(infos) != 15:' in text
    assert '"capture/predictions.json",' in text
    assert '"capture/source-evidence.json",' not in text
    assert '"capture/blind-review-template.json",' not in text
    assert 'source/netto/' not in text
    assert 'source.unlink()' in text
    assert 'promotion_ready") is not False' in text
    assert 'review_only") is not True' in text


def test_adjudication_artifact_sha256sums_keeps_required_two_space_separator() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sed \"s#  $output/##\"" not in text
    assert "digest=\"$(sha256sum \"$output/adjudication.json\" | cut -d' ' -f1)\"" in text
    assert "printf '%s  adjudication.json\\n' \"$digest\" > \"$output/SHA256SUMS\"" in text
