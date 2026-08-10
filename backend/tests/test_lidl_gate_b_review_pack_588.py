from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-gate-b-review-pack-588.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_exact_owner_issue_comment_gate() -> None:
    text = _text()
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]
    assert "github.event.issue.number == 588" in text
    assert "github.event.sender.login == 'rozkalnsandris'" in text
    assert "github.event.sender.id == 277435981" in text
    assert "github.event.comment.body == '/hermes-lidl-gate-b-review-pack-588'" in text
    assert text.count("github.event.comment.body") == 1
    assert "workflow_dispatch:" not in text
    assert "pull_request:" not in text
    assert "push:" not in text


def test_start_signal_is_not_authority_and_fixed_comments_are_verified() -> None:
    text = _text()
    for marker in (
        "AUTHORIZATION_COMMENT_ID: '5246346607'",
        "STATUS_COMMENT_ID: '5246347776'",
        "authorization.get('issue_url') != issue_url",
        "user.get('login') != 'rozkalnsandris'",
        "user.get('id') != 277435981",
        "Owner authorization — exact #588 visual review-pack generation",
        "Not authorized: RPi5/self-hosted execution",
        "`CORPUS_PROMOTION_AUTHORIZED=false`",
        "status.get('issue_url') != issue_url",
        "<!-- hermes-lidl-gate-b-review-pack-588-status -->",
    ):
        assert marker in text
    assert "authorization evidence mismatch" in text
    assert "authorization comment owner mismatch" in text
    assert "status comment marker mismatch" in text


def test_permissions_are_job_minimal_and_execution_is_github_hosted_only() -> None:
    text = _text()
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert parsed.get("permissions") == {}
    jobs = parsed["jobs"]
    assert jobs["authorize"]["permissions"] == {"issues": "read"}
    assert jobs["render"]["permissions"] == {}
    assert jobs["report"]["permissions"] == {"issues": "write"}
    assert jobs["authorize"]["runs-on"] == "ubuntu-24.04"
    assert jobs["render"]["runs-on"] == "ubuntu-24.04"
    assert jobs["report"]["runs-on"] == "ubuntu-24.04"
    assert "self-hosted" not in text
    assert "hermes-deals-audit" not in text
    assert "actions/checkout@" not in text
    assert "contents: read" not in text


def test_exact_source_identity_and_page_count_are_fail_closed_before_render() -> None:
    text = _text()
    source_url = (
        "https://object.storage.eu01.onstackit.cloud/leaflets/pdfs/"
        "019fc781-2e25-7b38-8816-a824a4f3f769/"
        "Aktionsprospekt-10-08-2026-15-08-2026-01.pdf"
    )
    digest_parts = (
        "ce84a4996f5c709620b8becc44c4e2a2",
        "3e23d24b28694679903490efc91ce728",
    )
    tree_parts = (
        "dd4ef887a72d6942bbade1adf8f2e2e2",
        "9c229675c8c28bb1f0b41c1082d4f4c1",
    )

    for marker in (
        source_url,
        f"PDF_ID_A: {digest_parts[0]}",
        f"PDF_ID_B: {digest_parts[1]}",
        f"TREE_ID_A: {tree_parts[0]}",
        f"TREE_ID_B: {tree_parts[1]}",
        'expected_pdf_digest="${PDF_ID_A}${PDF_ID_B}"',
        'staging_tree_digest="${TREE_ID_A}${TREE_ID_B}"',
        "EXPECTED_PAGE_COUNT: '73'",
        "FLYER_KEY: aktionsprospekt-10-08-2026-15-08-2026-71933b",
        "OFFICIAL_FLYER_ID: 019fc781-2e25-7b38-8816-a824a4f3f769",
        "ROUTE_REGION: '10'",
        "official PDF SHA-256 mismatch",
        "official PDF page count mismatch",
        "downloaded source is not a PDF",
    ):
        assert marker in text

    assert "".join(digest_parts) not in text
    assert "".join(tree_parts) not in text
    digest_gate = text.index('[[ "$actual_digest" == "$expected_pdf_digest" ]]')
    page_gate = text.index('[[ "$page_count" == "$EXPECTED_PAGE_COUNT" ]]')
    render_call = text.index("-jpegopt quality=88,optimize=y")
    assert digest_gate < page_gate < render_call


def test_visual_pack_is_bounded_and_excludes_raw_source() -> None:
    text = _text()
    for marker in (
        "-r 110",
        "-jpeg",
        "quality=88,optimize=y",
        "review-pack/pages",
        "page-{page:03d}.jpg",
        "review-pack/manifest.json",
        "review-pack/PAGE_SHA256SUMS",
        "raw_pdf_uploaded': False",
        "raw_source_json_uploaded': False",
        "retention-days: 7",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ):
        assert marker in text

    upload_block = text.split("- name: Upload bounded visual review pack", 1)[1].split("\n\n  report:", 1)[0]
    assert "path: review-pack" in upload_block
    assert "source.pdf" not in upload_block
    assert "source.json" not in upload_block


def test_manifest_and_report_keep_every_mutation_boundary_false() -> None:
    text = _text()
    for exact in (
        "'rpi5_execution': False",
        "'self_hosted_execution': False",
        "'corpus_write_performed': False",
        "'database_write_performed': False",
        "'review_write_performed': False",
        "'production_publish_performed': False",
        "'production_deploy_performed': False",
        "'systemd_change_performed': False",
        "'gate_c_d_authorized': False",
    ):
        assert exact in text

    for forbidden in (
        "ssh ",
        "scp ",
        "docker compose",
        "alembic ",
        "psql ",
        "systemctl ",
        "/home/andris/hermes-deals-lidl-corpus",
        "/usr/local/sbin/hermes-deals",
        "production_apply_authorized",
    ):
        assert forbidden not in text


def test_report_updates_fixed_marker_in_place() -> None:
    text = _text()
    assert "issues/comments/{os.environ['STATUS_COMMENT_ID']}" in text
    assert "method='PATCH'" in text
    assert "response.status != 200" in text
    assert "method='POST'" not in text
    assert "visual review pack — PASS" in text
    assert "visual review pack — BLOCKED" in text
    assert "raw PDF/source JSON are excluded" in text
