from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-gate-b-family-scan-554.yml"
DISPATCHER = ROOT / "tools" / "runner" / "lidl-gate-b-family-scan-554-dispatcher-v01.sh"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _dispatcher_text() -> str:
    return DISPATCHER.read_text(encoding="utf-8")


def test_workflow_is_exact_owner_start_signal_gate() -> None:
    text = _workflow_text()
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"issue_comment"}
    assert triggers["issue_comment"]["types"] == ["created"]

    assert "github.event.issue.number == 554" in text
    assert "github.event.sender.login == 'rozkalnsandris'" in text
    assert "github.event.sender.id == 277435981" in text
    assert "github.event.comment.body == '/hermes-lidl-gate-b-scan-554'" in text
    assert text.count("github.event.comment.body") == 1
    assert "workflow_dispatch:" not in text
    assert "pull_request:" not in text
    assert "push:" not in text


def test_start_signal_is_bound_to_recorded_authorization_evidence() -> None:
    text = _workflow_text()
    for marker in (
        "AUTHORIZATION_COMMENT_ID: '5238172572'",
        "STATUS_COMMENT_ID: '5245799786'",
        "authorization.get('issue_url') != issue_url",
        "user.get('login') != 'rozkalnsandris'",
        "user.get('id') != 277435981",
        "Owner explicitly authorized `#554 deterministic staging scan`.",
        "Allowed writes: private staging/evidence roots only.",
        "Still unauthorized: canonical corpus scan/profile promotion",
        "status.get('issue_url') != issue_url",
        "<!-- hermes-lidl-gate-b-scan-554-status -->",
    ):
        assert marker in text

    assert "authorization evidence mismatch" in text
    assert "authorization comment owner mismatch" in text
    assert "status comment marker mismatch" in text


def test_workflow_token_permissions_are_job_minimal() -> None:
    text = _workflow_text()
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert parsed.get("permissions") == {}
    jobs = parsed["jobs"]
    assert jobs["authorize"]["permissions"] == {"issues": "read"}
    assert jobs["scan"]["permissions"] == {}
    assert jobs["report"]["permissions"] == {"issues": "write"}
    assert "contents: read" not in text


def test_self_hosted_job_exposes_only_fixed_dispatcher() -> None:
    text = _workflow_text()
    assert "hermes-deals-audit" in text
    assert (
        "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-b-family-scan-554"
        in text
    )
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "retention-days: 30" in text
    assert "actions/checkout@" not in text

    for forbidden in (
        "github.event.comment.body }}",
        "eval ",
        "bash -c",
        "sh -c",
        "docker compose",
        "alembic ",
        "psql ",
        "systemctl ",
        "production_apply_authorized",
    ):
        assert forbidden not in text


def test_report_updates_one_fixed_status_comment_in_place() -> None:
    text = _workflow_text()
    assert "issues/comments/{os.environ['STATUS_COMMENT_ID']}" in text
    assert "method='PATCH'" in text
    assert "response.status != 200" in text
    assert "method='POST'" not in text
    assert "issues/{os.environ['ISSUE_NUMBER']}/comments" not in text
    assert "authorization evidence comment" in text
    assert "start-signal comment" in text


def test_workflow_sanitized_contract_contains_no_raw_row_export() -> None:
    text = _workflow_text()
    for required in (
        "byte_identical_replay",
        "frozen_family_unchanged",
        "corpus_write_performed",
        "database_write_performed",
        "review_write_performed",
        "production_publish_performed",
        "production_deploy_performed",
        "systemd_change_performed",
        "automatic_retry_performed",
        "gate_c_d_authorized",
    ):
        assert required in text
    for raw_name in (
        "source.pdf",
        "source.json",
        "parser-rows.json",
        "corrected-rows.json",
        "review-required.tsv",
        "accepted-physical.tsv",
    ):
        assert f"path: {raw_name}" not in text


def test_dispatcher_is_exact_source_and_runtime_bound() -> None:
    text = _dispatcher_text()
    for exact in (
        "EXPECTED_SHA='f53b58ec2ba05bb6f8ca02fd07ccbbed380e8b4e'",
        "EXPECTED_IMAGE='sha256:898dbfaba981ca7f583dcf2d6c623f9f407ce606760ebdb08f4e4be2f093174d'",
        "FLYER='aktionsprospekt-10-08-2026-15-08-2026-71933b'",
        "ROUTE_REGION='10'",
        "EXPECTED_PDF_SHA='ce84a4996f5c709620b8becc44c4e2a23e23d24b28694679903490efc91ce728'",
        "EXPECTED_RAW_SHA='12322c9989ea4038c7fb1e6d11e2728b6090e44958619b8cf4e5b22792f098fc'",
        "EXPECTED_STABLE_SHA='bf94419e77dcef693490df5e6dd43ff40fbf04847061843a7d17ef65087ad304'",
        "EXPECTED_PARSER_SHA='7191e910f07bb0a14ece3f398f1ba73e3ea250fc4bec1aeafea3afa8ce6dda90'",
        "EXPECTED_SCAN='scan-v631-7191e910f07b'",
    ):
        assert exact in text

    assert "[[ $# -eq 2 ]]" in text
    assert "GitHub run ID must be a positive integer" in text
    assert "GitHub run attempt must be a positive integer" in text


def test_dispatcher_docker_boundary_is_exact_family_read_only_and_staging_only() -> None:
    text = _dispatcher_text()
    for required in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges:true",
        "--pids-limit 256",
        "--memory 1536m",
        "--cpus 2",
        "src=$AUDIT_REPO,dst=/repo,readonly",
        "src=$FAMILY,dst=/frozen-family/$FLYER,readonly",
        ' --frozen-family "/frozen-family/$FLYER"',
        "python /repo/tools/lidl_gate_b_family_scan.py",
        'diff -qr "$STAGE_A" "$STAGE_B"',
        'cmp -s "$RUN_ROOT/scan-a-result.json" "$RUN_ROOT/scan-b-result.json"',
    ):
        assert required in text

    assert "src=$CORPUS_ROOT,dst=/corpus,readonly" not in text
    assert '--frozen-family "/corpus/flyers/$FLYER"' not in text

    for forbidden in (
        "docker compose",
        "alembic ",
        "psql ",
        "systemctl ",
        "apt ",
        "curl ",
        "wget ",
        "git checkout",
        "git reset",
        "git clean",
        "rm -rf $CORPUS_ROOT",
        "--privileged",
        "--network host",
        "docker.sock",
    ):
        assert forbidden not in text


def test_dispatcher_reports_all_mutation_boundaries_false() -> None:
    text = _dispatcher_text()
    for exact in (
        "'corpus_write_performed': False",
        "'database_write_performed': False",
        "'review_write_performed': False",
        "'production_publish_performed': False",
        "'production_deploy_performed': False",
        "'systemd_change_performed': False",
        "'automatic_retry_performed': False",
        "'gate_c_d_authorized': False",
    ):
        assert exact in text
