from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/netto-hz37-v2-adjudication.yml"


def test_hz37_v2_adjudication_is_distinct_owner_gated_and_never_auto_triggers() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "types:\n      - labeled" in text
    assert "audit:netto-hz37-adjudication-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "github.event_name == 'pull_request_target'" in text
    assert "github.event.action == 'labeled'" in text
    assert "push:" not in text
    assert "workflow_dispatch" not in text
    assert "audit:netto-heldout-adjudication-v1" not in text


def test_hz37_v2_adjudication_is_exactly_bound_to_retention_and_truth() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        'UPSTREAM_RUN_ID: "34132489970"',
        'UPSTREAM_ARTIFACT_ID: "10022687292"',
        "netto-heldout-v2-fbe3cfa143788607446d0095ae1f887354d10eb3-run-34132489970",
        "sha256:6a6394e91df0aab2681f7c042397cc4c572f4254e3f7df008840165f97cae2dc",
        'UPSTREAM_ARTIFACT_BYTES: "41514323"',
        "ee859fc903012a8c617caa63446ad889a4b4f237c324b9e6a43f2a792b43d52c",
        "a26ff71d73fee0c4189151279215a65ed2d54fbf",
        "049b6891d9f18c7c915f3b2c323aa312b3acd368",
        "40728fa509bda734490cc8763019b770ab5a0928",
        "tools/netto_hz37_v2_prediction_group_adjudication.py",
        "audit/netto/hz37/independent-retention-receipt.json",
        "audit/netto/hz37/completed-source-truth.json",
        "audit/netto/hz37/completed-source-truth-receipt.json",
    ):
        assert required in text


def test_hz37_v2_adjudication_preserves_checkout_and_production_boundaries() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "persist-credentials: false" in text
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0" in text
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "deploy-main",
        "actions/download-artifact",
    ):
        assert forbidden not in text
