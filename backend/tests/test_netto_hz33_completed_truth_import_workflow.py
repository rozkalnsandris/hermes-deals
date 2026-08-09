from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-completed-truth-import.yml"


def test_exact_truth_import_is_owner_gated_and_blob_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-hz33-completed-truth-import-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "EXPECTED_HEAD: feat/491-netto-hz33-completed-source-truth" in text
    assert "2972cc717bd7cb0156d766f80679c94d26123b2b" in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text
    assert 'EXPECTED_REVIEW_PACK_RUN: "31325617692"' in text
    assert "4962071277fbf4a49e9328dd20153cff2a9e566ff7a33381955f93c94015420a" in text
    assert "e47e1acc337f55dcdbbbfbbb5c200b3c100427ee5e022ad7d0e5e947e2f7274c" in text
    assert "9edd7f354fe8931dd0675e4876d344d700c1164499ecce19354903564649bb4a" in text


def test_exact_truth_import_never_executes_pr_code_or_crosses_production_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python tools/" not in text
    assert "python backend/" not in text
    assert "pytest" not in text
    assert "self-hosted" not in text
    assert "sudo " not in text
    assert "docker " not in text
    assert "psql " not in text
    assert "systemctl " not in text
    assert "/home/andris" not in text
    assert "predictions.json" not in text
    assert "single_source" in text  # only a forbidden truth-leak token
    assert "mixed_source" in text  # only a forbidden truth-leak token
    assert "excluded_control" in text  # only a forbidden truth-leak token


def test_exact_truth_import_writes_only_two_immutable_evidence_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit/netto/hz33/completed-source-truth.json.gz" in text
    assert "audit/netto/hz33/completed-source-truth-receipt.json" in text
    assert 'test "$(git diff --cached --name-only | wc -l)" -eq 2' in text
    assert 'git push origin "HEAD:${HEAD_REF}"' in text
