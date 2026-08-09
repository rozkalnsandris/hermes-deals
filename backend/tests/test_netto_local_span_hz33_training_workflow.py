from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/netto-local-span-hz33-training.yml"


def test_hz33_training_workflow_is_exact_and_owner_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "audit:netto-local-span-training-v1",
        "pull_request_target:",
        'EXPECTED_OWNER_ID: "277435981"',
        'UPSTREAM_RUN_ID: "31324156565"',
        "sha256:cc289165aaac8796b33391917edb03df1085a841b82d17fc08aa93efa1d66ec4",
        'UPSTREAM_ARTIFACT_BYTES: "37892979"',
        "49e22d29b16eacf0d316f20105de2c25e3d9b3c2ae231d0bd24d0d18036f5fd4",
        "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94",
        "completed-independent-source-truth-ledger.json.gz.b64",
        "netto_local_span_auto_single_training_audit.py",
    ):
        assert required in text


def test_hz33_training_workflow_uses_bounded_exact_artifact_extraction() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "if len(infos)!=15" in text
    assert '"capture/source-evidence.json"' in text
    assert '"capture/predictions.json"' in text
    assert '"capture/blind-review-template.json"' not in text
    assert "source/netto/" not in text
    assert "actions/download-artifact" not in text
    assert "zip_path.unlink()" in text


def test_hz33_training_workflow_keeps_training_and_production_boundaries() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("self-hosted", "sudo ", "docker ", "psql ", "systemctl ", "/home/andris", "deploy-main"):
        assert forbidden not in text
    assert 'candidate_auto_single_count")!=25' in text
    assert 'candidate_auto_single_precision")!=1.0' in text
    assert 'promotion_ready") is not False' in text
    assert "printf '%s  training-audit.json\\n'" in text
