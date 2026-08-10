from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-missing-normal-price-nonroot-preflight.yml"


def test_preflight_is_exact_owner_gated_non_root_and_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-missing-normal-price-nonroot" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert "EXPECTED_OWNER_ID: '277435981'" in text
    assert "trigger PR is not merged into repository main" in text
    assert "merge is not reachable from current main" in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert '[[ "$(id -un)" == "github-runner" ]]' in text
    assert '[[ "$(id -u)" -ne 0 ]]' in text
    assert "grep -Fxq docker" in text
    assert "sudo_used': False" in text
    assert "file_contents_exported': False" in text
    assert "database_write_performed': False" in text
    assert "review_write_performed': False" in text
    assert "deployment_performed': False" in text


def test_preflight_pins_exact_n9_and_both_authoritative_pdf_hashes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json" in text
    assert "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147" in text
    assert "/home/andris/hermes-deals-netto-corpus/flyers" in text
    assert "hz31_hasb_4" in text
    assert "9e878399868bd3ff5422954e7547ea68cfd2a518209ed01c96940a0eafb258ca" in text
    assert "hz32_hasb" in text
    assert "f87bb55bc735ecd7fbbf0735ad848615b30a543639a94265464d1c57e621cb36" in text
    assert "corpus-manifest.json" in text
    assert "source.pdf" in text
    assert "manifest_count'] == 1" in text


def test_preflight_exports_only_bounded_metadata_and_no_privileged_actions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "Non-root exact corpus ready" in text
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
