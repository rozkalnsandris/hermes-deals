from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-completed-truth-import-v2.yml"


def test_v2_exact_truth_import_is_owner_and_fresh_branch_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-hz33-completed-truth-import-v2" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "EXPECTED_HEAD: feat/491-netto-hz33-completed-source-truth-v2" in text
    assert "2972cc717bd7cb0156d766f80679c94d26123b2b" in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text
    assert 'EXPECTED_REVIEW_PACK_RUN: "31325617692"' in text
    assert "4962071277fbf4a49e9328dd20153cff2a9e566ff7a33381955f93c94015420a" in text


def test_v2_import_does_not_execute_pr_code_or_touch_production() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "python tools/",
        "python backend/",
        "pytest",
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "predictions.json",
    ):
        assert forbidden not in text
    assert 'git push origin "HEAD:${HEAD_REF}"' in text
    assert 'test "$(git diff --cached --name-only | wc -l)" -eq 2' in text
