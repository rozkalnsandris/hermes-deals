from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/netto-parent-unit-hz33-audit.yml"


def test_parent_unit_workflow_is_exact_owner_gated_and_hash_bound() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "audit:netto-parent-unit-v1",
        "pull_request_target:",
        'EXPECTED_OWNER_ID: "277435981"',
        'UPSTREAM_RUN_ID: "31324156565"',
        "netto-heldout-github-c0701d76bfa6412cbf89b4bf9816a68ccb3c2ab8-run-31324156565",
        "sha256:cc289165aaac8796b33391917edb03df1085a841b82d17fc08aa93efa1d66ec4",
        'UPSTREAM_ARTIFACT_BYTES: "37892979"',
        "49e22d29b16eacf0d316f20105de2c25e3d9b3c2ae231d0bd24d0d18036f5fd4",
        "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94",
        "capture/source-evidence.json",
        "capture/predictions.json",
        "capture/freeze-manifest.json",
        "capture/freeze-receipt.json",
        "capture/SHA256SUMS",
        "completed-independent-source-truth-ledger.json.gz.b64",
        "tools/netto_full_page_parent_unit_audit.py",
    ):
        assert required in text


def test_parent_unit_workflow_extracts_only_bounded_frozen_members() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'if len(infos) != 15:' in text
    for required in (
        '"SHA256SUMS",',
        '"capture/SHA256SUMS",',
        '"capture/freeze-manifest.json",',
        '"capture/freeze-receipt.json",',
        '"capture/source-evidence.json",',
        '"capture/predictions.json",',
    ):
        assert required in text
    for forbidden in (
        '"capture/blind-review-template.json",',
        '"capture/freeze-manifest.json.bak",',
        "source/netto/",
        "actions/download-artifact",
    ):
        assert forbidden not in text
    assert "source.unlink()" in text


def test_parent_unit_workflow_has_no_production_or_privileged_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "deploy-main",
        "kubectl ",
        "hz31_hasb_4",
        "hz32_hasb",
    ):
        assert forbidden not in text
    assert 'promotion_ready") is not False' in text
    assert 'review_only") is not True' in text


def test_parent_unit_artifact_sha256sums_uses_valid_two_space_format() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "digest=\"$(sha256sum \"$output/parent-unit-audit.json\" | cut -d' ' -f1)\"" in text
    assert "printf '%s  parent-unit-audit.json\\n' \"$digest\" > \"$output/SHA256SUMS\"" in text
