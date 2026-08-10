from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-missing-normal-price-nonroot-preflight-v2.yml"


def test_v2_preflight_is_owner_gated_non_root_and_permission_safe() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "audit:netto-missing-normal-price-nonroot-v2" in text
    assert "pull_request_target:" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert "EXPECTED_OWNER_ID: '277435981'" in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert '[[ "$(id -un)" == github-runner ]]' in text
    assert '[[ "$(id -u)" -ne 0 ]]' in text
    assert "grep -Fxq docker" in text
    assert '[[ -r "$N9_PATH" ]]' in text
    assert 'sha256sum -- "$N9_PATH" 2>/dev/null' in text
    assert 'stat -Lc' in text
    assert "n9_manifest_unreadable" in text
    assert "corpus_root_unreadable" in text
    assert "campaign_identity_probe_required" in text


def test_v2_preflight_pins_exact_n9_identity_and_safe_metadata_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json" in text
    assert "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147" in text
    assert "/home/andris/hermes-deals-netto-corpus/flyers" in text
    for token in (
        "'sudo_used':False",
        "'file_contents_exported':False",
        "'parser_executed':False",
        "'database_write_performed':False",
        "'review_write_performed':False",
        "'deployment_performed':False",
    ):
        assert token in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text


def test_v2_preflight_contains_no_privileged_or_mutating_actions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "sudo ",
        "chmod ",
        "chown ",
        "setfacl ",
        "docker ",
        "docker.sock",
        "psql ",
        "systemctl ",
        "alembic upgrade",
        "deploy-main",
        "actions/checkout",
    ):
        assert forbidden not in text
