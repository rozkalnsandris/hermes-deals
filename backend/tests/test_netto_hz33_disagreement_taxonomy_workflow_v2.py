from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-hz33-disagreement-taxonomy-v2.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_exact_owner_merged_pr_gated() -> None:
    text = _text()
    assert "pull_request_target:" in text
    assert "types: [labeled]" in text
    assert "audit:netto-hz33-disagreement-v2" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "EXPECTED_HEAD: feat/520-netto-hz33-disagreement-taxonomy-v2" in text
    assert '"merged": pr.get("merged") is True' in text
    assert 'event_path = Path(os.environ["GITHUB_EVENT_PATH"])' in text
    assert "missing GitHub event payload" in text
    assert "EVENT_PATH: ${{ github.event_path }}" not in text


def test_workflow_uses_only_committed_frozen_evidence() -> None:
    text = _text()
    assert "completed-independent-source-truth-ledger.json.gz.b64" in text
    assert "completed-source-truth-receipt.json" in text
    assert "audit/netto/hz33/heldout-adjudication.json" in text
    assert "audit/netto/hz33/heldout-adjudication-receipt.json" in text
    assert "1d1975c4845fe1bdbd2dd97670fac2df28cc68894003322485c10d53826a818f" in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text
    assert "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94" in text


def test_workflow_actions_are_immutable_and_permissions_are_read_only() -> None:
    text = _text()
    assert "permissions:\n  contents: read\n" in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "issues: write" not in text
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "actions/checkout@v" not in text
    assert "actions/upload-artifact@v" not in text
    assert "persist-credentials: false" in text


def test_workflow_explicitly_includes_validated_hidden_diagnostic_files() -> None:
    text = _text()
    assert "path: .hz33-diagnostic/" in text
    assert "include-hidden-files: true" in text
    assert "if-no-files-found: error" in text


def test_workflow_never_mutates_parser_or_production() -> None:
    text = _text().lower()
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "kubectl ",
        "git push",
        "repository_dispatch",
    ):
        assert forbidden not in text
    assert "threshold_tuning_performed" in text
    assert "parser_behavior_changed" in text
    assert '"review_only": true' in text
    assert '"promotion_ready": false' in text
