from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-completed-truth-import-v3.yml"


def test_v3_import_is_owner_branch_label_and_blob_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "EXPECTED_HEAD: feat/491-netto-hz33-completed-source-truth-v3" in text
    assert "EXPECTED_SEED: audit/netto/hz33/completed-source-truth-import-request-v3.json" in text
    assert "audit:netto-hz33-completed-truth-import-v3" in text
    assert "2972cc717bd7cb0156d766f80679c94d26123b2b" in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text
    assert 'EXPECTED_REVIEW_PACK_RUN: "31325617692"' in text
    assert "4962071277fbf4a49e9328dd20153cff2a9e566ff7a33381955f93c94015420a" in text
    assert "e47e1acc337f55dcdbbbfbbb5c200b3c100427ee5e022ad7d0e5e947e2f7274c" in text
    assert "9edd7f354fe8931dd0675e4876d344d700c1164499ecce19354903564649bb4a" in text


def test_v3_import_requires_exact_one_file_seed_delta() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "git fetch --no-tags origin main" in text
    assert "git merge-base --is-ancestor origin/main HEAD" in text
    assert "git diff --name-only origin/main...HEAD" in text
    assert 'test "${#changed[@]}" -eq 1' in text
    assert 'test "${changed[0]}" = "$EXPECTED_SEED"' in text
    assert '"strategy": "netto_hz33_completed_source_truth_import_request_v3"' in text
    assert "seed request binding mismatch" in text


def test_v3_external_action_is_immutable_and_push_credentials_are_explicitly_scoped() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    uses_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("uses: ")]
    assert uses_lines == [
        "uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2"
    ]
    action_ref = uses_lines[0].removeprefix("uses: ").split(maxsplit=1)[0]
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", action_ref)
    assert "actions/checkout@v4" not in text
    assert "persist-credentials: true" in text
    assert "Required only so this trusted base workflow can push the two allowlisted evidence files" in text


def test_v3_import_does_not_execute_pr_code_or_cross_production_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "python tools/",
        "python backend/",
        "pytest",
        "self-hosted",
        "sudo ",
        "docker ",
        "docker.sock",
        "psql ",
        "systemctl ",
        "/home/andris",
        "predictions.json",
        "alembic upgrade",
        "deploy-main",
    ):
        assert forbidden not in text
    assert 'git push origin "HEAD:${HEAD_REF}"' in text
    assert "audit/netto/hz33/completed-source-truth.json.gz" in text
    assert "audit/netto/hz33/completed-source-truth-receipt.json" in text
    assert 'test "${#staged[@]}" -eq 2' in text
    assert "production/DB/Review/deploy: **false**" in text
