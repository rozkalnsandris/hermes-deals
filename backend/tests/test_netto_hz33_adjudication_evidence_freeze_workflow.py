from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-adjudication-evidence-freeze.yml"


def test_freezer_is_exact_owner_and_evidence_branch_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-hz33-adjudication-freeze-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "EXPECTED_HEAD: feat/netto-hz33-adjudication-evidence-v1" in text
    assert 'CAPTURE_RUN_ID: "31324156565"' in text
    assert 'CAPTURE_ARTIFACT_ID: "9041052231"' in text
    assert "cc289165aaac8796b33391917edb03df1085a841b82d17fc08aa93efa1d66ec4" in text
    assert "ddcf664eca4d1305fa9d3984de8d59b37af83b9a3820d26fc2155bf0af32f6b6" in text


def test_freezer_executes_only_trusted_main_code() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Checkout trusted exact main base" in text
    assert 'test "$(git rev-parse origin/main)" = "$BASE_SHA"' in text
    assert 'test "$(git diff --name-only "$BASE_SHA..$HEAD_SHA" | wc -l)" -eq 1' in text
    assert 'test "$(git diff --name-only "$BASE_SHA..$HEAD_SHA")" = "$SEED_PATH"' in text
    assert "python tools/netto_heldout_hz33_adjudication.py" in text


def test_freezer_writes_only_two_adjudication_evidence_files() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit/netto/hz33/heldout-adjudication.json" in text
    assert "audit/netto/hz33/heldout-adjudication-receipt.json" in text
    assert 'test "$(git diff --cached --name-only | wc -l)" -eq 2' in text
    assert 'git push origin "HEAD:${HEAD_REF}"' in text
    assert "promotion_ready" in text
    assert "acceptance_pass" in text


def test_freezer_never_crosses_production_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "kubectl ",
    ):
        assert forbidden not in text
    assert "--require-acceptance" not in text
    assert "heldout-adjudication-import-request.json" in text
