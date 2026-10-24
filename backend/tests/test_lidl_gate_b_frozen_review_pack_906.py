from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools" / "runner" / "lidl-gate-b-frozen-review-pack-906-dispatcher-v01.sh"
INSTALLER = ROOT / "tools" / "runner" / "install-lidl-gate-b-frozen-review-pack-906-dispatcher-v01.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-gate-b-frozen-review-pack-906.yml"

FAMILY = "aktionsprospekt-26-10-2026-31-10-2026-fef8e1"
PDF_SHA = "eb7de20caeb74f86b5a76c808986cb3f88beca0b67e3f01d6f9841e89ba18002"
SCAN_TREE = "58b4d56eb87dd16ef4f07be77d4c32769993eddd4f5b2e563def532df0308894"
DISPATCHER_BLOB = "8a230ec7feabcae1c14b9d14b0fa40c9d6b73a6e"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dispatcher_is_exact_frozen_source_only() -> None:
    text = read(DISPATCHER)
    assert "lidl-gate-b-frozen-review-pack-906-dispatcher-v01" in text
    assert FAMILY in text
    assert PDF_SHA in text
    assert "EXPECTED_PAGE_COUNT='76'" in text
    assert SCAN_TREE in text
    assert "/home/andris/hermes-deals-audit-source" in text
    assert "/var/lib/hermes-deals/lidl-gate-b-frozen-review-pack-906" in text
    assert "[[ $# -eq 2 ]]" in text
    assert "source.pdf" in text
    assert "stat -c '%U:%G %a' \"$FAMILY\"" in text
    assert "andris:andris 700" in text
    assert "andris:andris 600" in text
    assert "readlink -f -- \"$SOURCE_PDF\"" in text
    assert "sha256sum \"$SOURCE_PDF\"" in text
    assert "pdfinfo \"$SOURCE_PDF\"" in text
    assert "http://" not in text and "https://" not in text
    assert "curl " not in text and "wget " not in text


def test_dispatcher_renders_twice_and_exports_only_sanitized_assets() -> None:
    text = read(DISPATCHER)
    assert 'render_stage "$STAGE_A"' in text
    assert 'render_stage "$STAGE_B"' in text
    assert "runuser -u andris -- pdftoppm" in text
    assert "-r 110" in text
    assert "-jpeg" in text
    assert "quality=88,optimize=y" in text
    assert 'diff -qr "$STAGE_A" "$STAGE_B"' in text
    assert "BYTE_IDENTICAL_PASS" in text
    assert "FAMILY_TREE_BEFORE" in text and "FAMILY_TREE_AFTER" in text
    assert "PRIMARY_BEFORE" in text and "PRIMARY_AFTER" in text
    assert "AUDIT_BEFORE" in text and "AUDIT_AFTER" in text
    assert "ARTIFACT_DIR/pages" in text
    assert "PAGE_SHA256SUMS" in text
    assert "manifest.json" in text
    assert "summary.json" in text
    assert "'raw_pdf_uploaded': False" in text
    assert "'source_content_exported': False" in text
    assert '[[ ! -e "$ARTIFACT_DIR/source.pdf" ]]' in text
    assert "docker run" not in text
    for marker in (
        "'corpus_write': False",
        "'corpus_replacement': False",
        "'production_database_write': False",
        "'review_write': False",
        "'production_publish': False",
        "'production_deploy': False",
        "'systemd_change': False",
        "'automatic_retry': False",
        "'gate_c_d_authorized': False",
    ):
        assert marker in text


def test_installer_is_checksum_bound_and_registration_only() -> None:
    text = read(INSTALLER)
    assert "<merged-main-sha>" in text
    assert f"EXPECTED_DISPATCHER_BLOB='{DISPATCHER_BLOB}'" in text
    assert FAMILY in text
    assert PDF_SHA in text
    assert "== '76'" in text
    assert "merge-base --is-ancestor" in text
    assert "hash-object --stdin" in text
    assert "github-runner must not belong to the Docker group" in text
    assert "host Sudo is older than 1.9.10" in text
    assert "^[1-9][0-9]* [1-9][0-9]*$" in text
    assert "LIVE_RENDER_PERFORMED=false" in text
    assert "LIDL_GATE_B_FROZEN_REVIEW_PACK_906_REGISTRATION=PASS" in text
    assert '"$DISPATCHER" "$GITHUB_RUN_ID"' not in text
    assert "-jpeg" not in text


def test_workflow_authorization_is_owner_bound_and_one_shot() -> None:
    text = read(WORKFLOW)
    assert "issue_comment:" in text
    assert "github.event.issue.number == 906" in text
    assert "github.event.sender.login == 'rozkalnsandris'" in text
    assert "github.event.sender.id == 277435981" in text
    assert "/hermes-lidl-gate-b-frozen-review-pack-906 auth=" in text
    assert "issues/906" in text
    assert "authorization comment issue mismatch" in text
    assert "authorization comment owner mismatch" in text
    assert "authorization comment was already consumed by a prior render attempt" in text
    assert "LIDL-GATE-B-FROZEN-REVIEW-PACK-ONCE" in text
    assert FAMILY in text
    assert PDF_SHA in text
    assert "PAGE-COUNT=76" in text
    assert SCAN_TREE in text
    for marker in (
        "ONE_CONTROLLED_RENDER=true",
        "RPI5_EXECUTION_AUTHORIZED=true",
        "SELF_HOSTED_EXECUTION_AUTHORIZED=true",
        "CORPUS_WRITE=false",
        "CORPUS_REPLACEMENT=false",
        "PRODUCTION_DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "PRODUCTION_PUBLISH=false",
        "PRODUCTION_DEPLOY=false",
        "SYSTEMD_CHANGE=false",
        "AUTOMATIC_RETRY=false",
        "GATE_C_D_AUTHORIZED=false",
    ):
        assert marker in text


def test_workflow_self_hosted_job_has_no_checkout_and_only_fixed_dispatcher() -> None:
    text = read(WORKFLOW)
    render = text.split("  render:\n", 1)[1].split("\n  report:\n", 1)[0]
    assert "self-hosted" in render
    assert "Linux" in render and "ARM64" in render and "hermes-deals-audit" in render
    assert "permissions: {}" in render
    assert "actions/checkout" not in render
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-b-frozen-review-pack-906" in render
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in render
    assert "/var/lib/hermes-deals/lidl-gate-b-frozen-review-pack-906/" in render
    assert "curl " not in render and "wget " not in render
    assert "source.pdf" not in render


def test_workflow_validates_sanitized_summary_and_reports_without_retry() -> None:
    text = read(WORKFLOW)
    assert '"audit": "lidl-gate-b-frozen-review-pack-906"' in text
    assert '"page_count": 76' in text
    assert '"independent_render_replay": "BYTE_IDENTICAL_PASS"' in text
    assert '"corpus_write": False' in text
    assert '"review_write": False' in text
    assert '"production_publish": False' in text
    assert '"production_deploy": False' in text
    assert '"automatic_retry": False' in text
    assert '"gate_c_d_authorized": False' in text
    assert "method=\"POST\"" in text
    assert "issues/906/comments" in text
    assert "<!-- hermes-lidl-gate-b-frozen-review-pack-906-status -->" in text
    report = text.split("  report:\n", 1)[1]\n    assert "rerun" not in report.lower()\n    assert "workflow_dispatch" not in report


def test_workflow_uploads_no_raw_pdf_or_corpus_path() -> None:
    text = read(WORKFLOW)
    assert "object.storage.eu01.onstackit.cloud" not in text
    assert "path: /home/andris/hermes-deals-lidl-corpus" not in text
    assert re.search(
        r"path:\s*/var/lib/hermes-deals/lidl-gate-b-frozen-review-pack-906/.+/artifact",
        text,
    )
