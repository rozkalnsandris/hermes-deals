from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz33-adjudication-evidence-freeze.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v2_freezer_is_exact_owner_branch_and_label_gated() -> None:
    text = _text()
    assert "pull_request_target:" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "EXPECTED_HEAD: feat/netto-hz33-adjudication-evidence-v2" in text
    assert "TRIGGER_LABEL: audit:netto-hz33-adjudication-freeze-v2" in text
    assert "heldout-adjudication-import-request-v2.json" in text
    assert "evidence PR base is not current main" in text
    assert "exactly one commit ahead and zero behind" in text
    assert "v2 seed request binding mismatch" in text


def test_v2_freezer_binds_the_verified_post_fix_artifact_exactly() -> None:
    text = _text()
    assert 'ADJUDICATION_RUN_ID: "31329528400"' in text
    assert 'ADJUDICATION_ARTIFACT_ID: "9042509363"' in text
    assert "10f778b802d6a36d831e05e996052f91a098e11c9a53d2e062df3ce6e4e12867" in text
    assert 'ADJUDICATION_ARTIFACT_SIZE_BYTES: "25285"' in text
    assert "1d1975c4845fe1bdbd2dd97670fac2df28cc68894003322485c10d53826a818f" in text
    assert "83a6efd4ee00442e660b637efadf655158963de6837335232e37b79e34846adc" in text
    assert 'expected_line = f"{expected_json_sha}  adjudication.json\\n"' in text
    assert "adjudication artifact ZIP byte identity mismatch" in text
    assert "adjudication.json SHA256 mismatch" in text


def test_v2_freezer_preserves_not_evaluable_and_nonpromotion_contract() -> None:
    text = _text()
    assert '"required_metric_not_evaluable_count": 2' in text
    assert '"acceptance_all_pass": False' in text
    assert '"recomputed_during_freeze": False' in text
    assert '"review_only": True' in text
    assert '"promotion_ready": False' in text
    assert '"database_write_performed": False' in text
    assert '"review_write_performed": False' in text
    assert '"deployment_performed": False' in text


def test_v2_freezer_never_executes_pr_or_repository_code() -> None:
    text = _text()
    assert not [line for line in text.splitlines() if line.strip().startswith("uses:")]
    for forbidden in (
        "actions/checkout@",
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
        "alembic upgrade",
        "deploy-main",
    ):
        assert forbidden not in text


def test_v2_freezer_writes_only_two_create_only_evidence_paths() -> None:
    text = _text()
    assert "EVIDENCE_JSON: audit/netto/hz33/heldout-adjudication.json" in text
    assert "EVIDENCE_RECEIPT: audit/netto/hz33/heldout-adjudication-receipt.json" in text
    assert "evidence output already exists" in text
    assert '"mode": "100644", "type": "blob"' in text
    assert '"parents": [expected_head]' in text
    assert '"force": False' in text
    assert "evidence branch moved during freeze commit" in text


def test_v21_freezer_rechecks_current_main_before_evidence_ref_update() -> None:
    text = _text()
    assert "BASE_SHA: ${{ needs.authorize.outputs.base_sha }}" in text
    assert 'expected_base = os.environ["BASE_SHA"]' in text
    assert 'request("GET", "git/ref/heads/main")' in text
    assert "main moved before freeze commit" in text
    assert "main moved during freeze commit" in text
    assert text.index("main moved before freeze commit") < text.index('request(\n              "PATCH"')
    assert text.index("main moved during freeze commit") < text.index('request(\n              "PATCH"')


def test_v2_freezer_has_no_mutable_external_action_refs() -> None:
    text = _text()
    uses_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("uses:")]
    assert uses_lines == []
    assert re.search(r"permissions:\n  contents: read", text)
    assert "contents: write" in text
    assert "actions: read" in text
