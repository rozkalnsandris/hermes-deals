from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-hz34-blind-review-pack.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_hz34_review_pack_workflow_is_owner_gated_and_github_hosted() -> None:
    text = _text()
    assert "pull_request_target:" in text
    assert "audit:netto-hz34-blind-review-pack-v1" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text
    assert "sudo " not in text
    assert "systemctl" not in text
    assert "docker compose" not in text
    assert "workflow_dispatch:" not in text


def test_hz34_review_pack_workflow_pins_external_actions_to_full_shas() -> None:
    text = _text()
    refs = re.findall(r"^\s*uses:\s*([^@\s]+)@([^\s#]+)", text, flags=re.MULTILINE)
    assert refs == [
        ("actions/checkout", "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"),
        ("actions/setup-python", "a309ff8b426b58ec0e2a45f0f869d46889d02405"),
        ("actions/upload-artifact", "ea165f8d65b6e75b540449e92b4886f43607fa02"),
    ]
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for _, sha in refs)


def test_hz34_review_pack_workflow_binds_exact_frozen_input_and_runtime() -> None:
    text = _text()
    for token in (
        'UPSTREAM_ARTIFACT_ID: "9362894718"',
        'UPSTREAM_RUN_ID: "32246715725"',
        "sha256:d99d955ca678e9ffc4b40566bf2e8bdd32b1994e43460ba470472bcbe356d651",
        'UPSTREAM_ARTIFACT_BYTES: "35113989"',
        "UPSTREAM_COMMIT: 59483092edf2d378e3ef44ac4c92dac3bbc597a2",
        "EXPECTED_CAMPAIGN: hz34_hasb",
        'EXPECTED_VALID_FROM: "2026-08-17"',
        'EXPECTED_VALID_UNTIL: "2026-08-22"',
        "1fdb1a20b09f9d23663f4ff052fe412591eab799033262447708fd85e4058465",
        "b92d7ace8428d49daf0658d769af88b1b0ef3fcd31e4244a00aeaf0150277169",
        "0ca98977d2870e13a8ec985db6c90258fbe6276dc24737d606b739c6517ae4c8",
        "f74fc51cac686bad54940c0bbf39f659c3554c6b97ea50a8960321b989aebb42",
        'EXPECTED_PAGE_COUNT: "70"',
        'PYMUPDF_VERSION: "1.28.0"',
        "pymupdf-1.28.0-cp310-abi3-manylinux_2_28_x86_64.whl",
        "44f0973f5e5edbaec95bc34b64e71d1959d4ee90b1328de1b4f4f5b4fa78673f",
        'python-version: "3.13.12"',
    ):
        assert token in text


def test_hz34_review_pack_workflow_never_forwards_github_auth_to_signed_storage() -> None:
    text = _text()
    assert "class NoRedirect" in text
    assert "error.code != 302" in text
    assert "Deliberately do not forward GitHub Authorization to the signed storage URL." in text
    assert "urllib.request.urlopen(location, timeout=120)" in text


def test_hz34_review_pack_workflow_runs_exact_adapter_twice_and_verifies_output() -> None:
    text = _text()
    assert text.count("tools/netto_heldout_blind_artifact_pack.py") == 2
    assert '--output "$pack_a"' in text
    assert '--output "$pack_b"' in text
    assert "second build is not byte-for-byte deterministic" in text
    assert 'verify_sum_file(a, "SHA256SUMS")' in text
    assert 'verify_sum_file(a, "ARTIFACT-SHA256SUMS")' in text
    assert "blank_before_independent_source_card_review" in text
    assert "forbidden upstream candidate/prediction member reached reviewer pack" in text


def test_hz34_review_pack_workflow_uploads_only_safe_pack_and_keeps_truth_blocked() -> None:
    text = _text()
    upload_section = text.split("- name: Upload reviewer-safe pack only", 1)[1].split("\n  report:", 1)[0]
    assert "actions/upload-artifact@" in upload_section
    assert "path: ${{ steps.generate.outputs.pack_a }}" in upload_section
    assert "ZIP_PATH" not in upload_section
    assert "predictions.json" not in upload_section
    assert "candidate-provenance.json" not in upload_section
    assert "truth creation/import/adjudication remains separately owner-gated" in text
    assert "database_write_performed" in text
    assert "review_write_performed" in text
    assert "publication_write_performed" in text
    assert "deployment_performed" in text


def test_hz34_review_pack_report_preserves_run_and_job_identity() -> None:
    text = _text()
    for token in (
        "RUN_ID: ${{ github.run_id }}",
        "RUN_ATTEMPT: ${{ github.run_attempt }}",
        "SERVER_URL: ${{ github.server_url }}",
        "AUTHORIZE_RESULT: ${{ needs.authorize.result }}",
        "PACK_RESULT: ${{ needs.pack.result }}",
        "actions/runs/{os.environ['RUN_ID']}",
        "workflow run ID:",
        "workflow run attempt:",
        "Actions run:",
        "authorize job result:",
        "pack job result:",
        "runtime merge SHA:",
    ):
        assert token in text
    assert "identity = (" in text
    assert '"## Netto hz34 blind reviewer-pack retry — PASS\\n\\n"\n                  + identity' in text
    assert '"## Netto hz34 blind reviewer-pack retry — BLOCKED/FAIL\\n\\n"\n                  + identity' in text


def test_hz34_review_pack_authorizer_accepts_only_four_file_remediation_pr() -> None:
    text = _text()
    assert "expected_files = {" in text
    for path in (
        ".github/workflows/netto-hz34-blind-review-pack.yml",
        "backend/tests/test_netto_hz34_blind_review_pack_workflow.py",
        "tools/netto_heldout_blind_artifact_pack.py",
        "backend/tests/test_netto_heldout_blind_artifact_pack.py",
    ):
        assert f'"{path}"' in text
    assert "if set(files) != expected_files:" in text


def test_hz34_review_pack_report_can_clear_label_from_merged_pr() -> None:
    text = _text()
    report = text.split("\n  report:\n", 1)[1]
    assert "issues: write" in report
    assert "pull-requests: write" in report
    assert 'method="DELETE"' in report
    assert "/labels/{encoded}" in report
