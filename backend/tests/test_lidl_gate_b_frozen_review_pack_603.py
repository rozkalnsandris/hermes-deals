from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools/runner/lidl-gate-b-frozen-review-pack-603-dispatcher-v01.sh"
INSTALLER = ROOT / "tools/runner/install-lidl-gate-b-frozen-review-pack-603-dispatcher-v01.sh"
WORKFLOW = ROOT / ".github/workflows/hermes-lidl-gate-b-frozen-review-pack-603.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dispatcher_is_exact_frozen_source_only() -> None:
    text = read(DISPATCHER)
    assert "[[ $# -eq 2 ]]" in text
    assert "github-run-id" in text and "github-run-attempt" in text
    assert "/home/andris/hermes-deals-lidl-corpus" in text
    assert "aktionsprospekt-10-08-2026-15-08-2026-71933b" in text
    assert "source.pdf" in text
    assert "ce84a4996f5c709620b8becc44c4e2a23e23d24b28694679903490efc91ce728" in text
    assert "EXPECTED_PAGE_COUNT='73'" in text
    assert "dd4ef887a72d6942bbade1adf8f2e2e29c229675c8c28bb1f0b41c1082d4f4c1" in text
    assert "stat -c '%U:%G %a' \"$FAMILY\"" in text
    assert "andris:andris 700" in text
    assert "andris:andris 600" in text
    assert "readlink -f -- \"$SOURCE_PDF\"" in text
    assert "sha256sum \"$SOURCE_PDF\"" in text
    assert "pdfinfo \"$SOURCE_PDF\"" in text
    assert "-01.pdf" not in text
    assert "-02.pdf" not in text
    assert "http://" not in text and "https://" not in text
    assert "curl " not in text and "wget " not in text


def test_dispatcher_renders_twice_as_unprivileged_andris_and_fails_closed() -> None:
    text = read(DISPATCHER)
    assert "render_stage \"$STAGE_A\"" in text
    assert "render_stage \"$STAGE_B\"" in text
    assert "runuser -u andris -- pdftoppm" in text
    assert "-r 110" in text
    assert "-jpeg" in text
    assert "quality=88,optimize=y" in text
    assert "diff -qr \"$STAGE_A\" \"$STAGE_B\"" in text
    assert "RENDER_TREE_A" in text and "RENDER_TREE_B" in text
    assert "BYTE_IDENTICAL_PASS" in text
    assert "FAMILY_TREE_BEFORE" in text and "FAMILY_TREE_AFTER" in text
    assert "SOURCE_STAT_BEFORE" in text and "SOURCE_STAT_AFTER" in text
    assert "PRIMARY_BEFORE" in text and "PRIMARY_AFTER" in text
    assert "AUDIT_BEFORE" in text and "AUDIT_AFTER" in text
    assert "github-runner must not belong to the Docker group" in text
    assert "docker run" not in text


def test_dispatcher_exports_only_sanitized_review_assets() -> None:
    text = read(DISPATCHER)
    assert "/var/lib/hermes-deals/lidl-gate-b-frozen-review-pack-603" in text
    assert "ARTIFACT_DIR/pages" in text
    assert "PAGE_SHA256SUMS" in text
    assert "manifest.json" in text
    assert "summary.json" in text
    assert "raw_pdf_uploaded': False" in text
    assert "source_content_exported': False" in text
    assert "[[ ! -e \"$ARTIFACT_DIR/source.pdf\" ]]" in text
    assert "install -o root -g root -m 0644 \"$image\"" in text
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
    assert "[[ ${EUID:-$(id -u)} -eq 0 ]]" in text
    assert "<merged-main-sha>" in text
    assert "EXPECTED_DISPATCHER_BLOB='1f2aa55657056834c54cd7ba6d1ffd3b68c2b133'" in text
    assert "merge-base --is-ancestor" in text
    assert "hash-object --stdin < \"$TMP/dispatcher\"" in text
    assert "github-runner must not belong to the Docker group" in text
    assert "host Sudo is older than 1.9.10" in text
    assert "^[1-9][0-9]* [1-9][0-9]*$" in text
    assert "sudo -n -l -U github-runner -- \"$DISPATCHER\" 1 1" in text
    for malformed in (
        "sudo_policy_must_deny 0 1",
        "sudo_policy_must_deny 1 0",
        "sudo_policy_must_deny x 1",
        "sudo_policy_must_deny 1 x",
        "sudo_policy_must_deny 1\n",
        "sudo_policy_must_deny 1 1 extra",
    ):
        assert malformed in text
    assert "LIVE_RENDER_PERFORMED=false" in text
    assert "\"$DISPATCHER\" \"$GITHUB_RUN_ID\"" not in text
    assert "pdftoppm -v" in text
    assert "-jpeg" not in text


def test_workflow_authorization_is_owner_bound_one_shot_and_dynamic_id() -> None:
    text = read(WORKFLOW)
    assert "issue_comment:" in text
    assert "github.event.issue.number == 603" in text
    assert "github.event.sender.login == 'rozkalnsandris'" in text
    assert "github.event.sender.id == 277435981" in text
    assert "/hermes-lidl-gate-b-frozen-review-pack-603 auth=" in text
    assert "re.fullmatch(r'/hermes-lidl-gate-b-frozen-review-pack-603 auth=([1-9][0-9]*)'" in text
    assert "issues: read" in text
    assert "authorization comment issue mismatch" in text
    assert "authorization comment owner mismatch" in text
    assert "ONE_CONTROLLED_RENDER=true" in text
    assert "RPI5_EXECUTION_AUTHORIZED=true" in text
    assert "SELF_HOSTED_EXECUTION_AUTHORIZED=true" in text
    assert "authorization comment was already consumed" in text
    assert "STATUS_COMMENT_ID: '5246347776'" in text
    assert "issues/588" in text


def test_workflow_self_hosted_job_has_no_checkout_and_only_fixed_dispatcher() -> None:
    text = read(WORKFLOW)
    render = text.split("  render:\n", 1)[1].split("\n  report:\n", 1)[0]
    assert "self-hosted" in render
    assert "Linux" in render and "ARM64" in render and "hermes-deals-audit" in render
    assert "permissions: {}" in render
    assert "actions/checkout" not in render
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-b-frozen-review-pack-603" in render
    assert '"$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT"' in render
    assert "curl " not in render and "wget " not in render
    assert "source.pdf" not in render
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in render
    assert "/var/lib/hermes-deals/lidl-gate-b-frozen-review-pack-603/${{ github.run_id }}-${{ github.run_attempt }}/artifact" in render


def test_workflow_summary_and_report_keep_mutation_flags_false() -> None:
    text = read(WORKFLOW)
    assert "source_pdf_sha256': 'ce84a4996f5c709620b8becc44c4e2a23e23d24b28694679903490efc91ce728'" in text
    assert "'page_count': 73" in text
    assert "'independent_render_replay': 'BYTE_IDENTICAL_PASS'" in text
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
    report = text.split("  report:\n", 1)[1]
    assert "issues: write" in report
    assert "method='PATCH'" in report
    assert "issues/comments/{os.environ['STATUS_COMMENT_ID']}" in report
    assert "No corpus replacement/promotion" in report


def test_workflow_does_not_embed_live_lidl_pdf_or_raw_pdf_upload() -> None:
    text = read(WORKFLOW)
    assert "object.storage.eu01.onstackit.cloud" not in text
    assert "Aktionsprospekt-10-08-2026-15-08-2026-01.pdf" not in text
    assert "Aktionsprospekt-10-08-2026-15-08-2026-02.pdf" not in text
    assert re.search(r"path:\s*/var/lib/hermes-deals/.+/artifact", text)
    assert "path: /home/andris/hermes-deals-lidl-corpus" not in text
